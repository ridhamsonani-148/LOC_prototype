import * as cdk from 'aws-cdk-lib';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as neptune from 'aws-cdk-lib/aws-neptune';
import * as apigateway from 'aws-cdk-lib/aws-apigateway';
import * as stepfunctions from 'aws-cdk-lib/aws-stepfunctions';
import * as tasks from 'aws-cdk-lib/aws-stepfunctions-tasks';
import * as logs from 'aws-cdk-lib/aws-logs';
import { Construct } from 'constructs';
import * as path from 'path';

export interface ChroniclingAmericaStackProps extends cdk.StackProps {
  projectName: string;
  dataBucketName?: string;
  bedrockModelId?: string;
}

export class ChroniclingAmericaStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props: ChroniclingAmericaStackProps) {
    super(scope, id, props);

    const projectName = props.projectName;
    const bedrockModelId = props.bedrockModelId || 'anthropic.claude-3-5-sonnet-20241022-v2:0';

    // ========================================
    // S3 Bucket for Data Storage
    // ========================================
    const dataBucket = new s3.Bucket(this, 'DataBucket', {
      bucketName: props.dataBucketName || `${projectName}-data-${this.account}-${this.region}`,
      encryption: s3.BucketEncryption.S3_MANAGED,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      removalPolicy: cdk.RemovalPolicy.RETAIN,
      lifecycleRules: [
        {
          id: 'DeleteOldExtractions',
          expiration: cdk.Duration.days(90),
          prefix: 'extracted/',
        },
      ],
    });

    // ========================================
    // VPC for Neptune
    // ========================================
    const vpc = new ec2.Vpc(this, 'NeptuneVPC', {
      maxAzs: 2,
      natGateways: 1,
      subnetConfiguration: [
        {
          cidrMask: 24,
          name: 'Public',
          subnetType: ec2.SubnetType.PUBLIC,
        },
        {
          cidrMask: 24,
          name: 'Private',
          subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS,
        },
        {
          cidrMask: 28,
          name: 'Isolated',
          subnetType: ec2.SubnetType.PRIVATE_ISOLATED,
        },
      ],
    });

    // Security Group for Neptune
    const neptuneSecurityGroup = new ec2.SecurityGroup(this, 'NeptuneSecurityGroup', {
      vpc,
      description: 'Security group for Neptune cluster',
      allowAllOutbound: true,
    });

    neptuneSecurityGroup.addIngressRule(
      neptuneSecurityGroup,
      ec2.Port.tcp(8182),
      'Allow Neptune access from within security group'
    );

    // ========================================
    // Neptune Cluster
    // ========================================
    const neptuneSubnetGroup = new neptune.CfnDBSubnetGroup(this, 'NeptuneSubnetGroup', {
      dbSubnetGroupDescription: 'Subnet group for Neptune cluster',
      subnetIds: vpc.isolatedSubnets.map(subnet => subnet.subnetId),
      dbSubnetGroupName: `${projectName}-neptune-subnet-group`,
    });

    const neptuneCluster = new neptune.CfnDBCluster(this, 'NeptuneCluster', {
      dbClusterIdentifier: `${projectName}-neptune-cluster`,
      dbSubnetGroupName: neptuneSubnetGroup.dbSubnetGroupName,
      vpcSecurityGroupIds: [neptuneSecurityGroup.securityGroupId],
      iamAuthEnabled: false,
      storageEncrypted: true,
    });

    neptuneCluster.addDependency(neptuneSubnetGroup);

    const neptuneInstance = new neptune.CfnDBInstance(this, 'NeptuneInstance', {
      dbInstanceClass: 'db.t3.medium',
      dbClusterIdentifier: neptuneCluster.dbClusterIdentifier,
      dbInstanceIdentifier: `${projectName}-neptune-instance`,
    });

    neptuneInstance.addDependency(neptuneCluster);

    // ========================================
    // Lambda Execution Role
    // ========================================
    const lambdaRole = new iam.Role(this, 'LambdaExecutionRole', {
      assumedBy: new iam.ServicePrincipal('lambda.amazonaws.com'),
      managedPolicies: [
        iam.ManagedPolicy.fromAwsManagedPolicyName('service-role/AWSLambdaVPCAccessExecutionRole'),
        iam.ManagedPolicy.fromAwsManagedPolicyName('service-role/AWSLambdaBasicExecutionRole'),
      ],
    });

    // Grant S3 permissions
    dataBucket.grantReadWrite(lambdaRole);

    // Grant Bedrock permissions
    lambdaRole.addToPolicy(new iam.PolicyStatement({
      effect: iam.Effect.ALLOW,
      actions: [
        'bedrock:InvokeModel',
        'bedrock:InvokeModelWithResponseStream',
      ],
      resources: [`arn:aws:bedrock:${this.region}::foundation-model/*`],
    }));

    // Grant Neptune permissions
    lambdaRole.addToPolicy(new iam.PolicyStatement({
      effect: iam.Effect.ALLOW,
      actions: [
        'neptune-db:*',
      ],
      resources: ['*'],
    }));

    // ========================================
    // Lambda Functions (Docker-based)
    // ========================================

    // 1. Image Collector Lambda
    const imageCollectorFunction = new lambda.DockerImageFunction(this, 'ImageCollectorFunction', {
      functionName: `${projectName}-image-collector`,
      code: lambda.DockerImageCode.fromImageAsset(path.join(__dirname, '../lambda/image-collector')),
      timeout: cdk.Duration.minutes(15),
      memorySize: 1024,
      role: lambdaRole,
      environment: {
        DATA_BUCKET: dataBucket.bucketName,
      },
      logRetention: logs.RetentionDays.ONE_WEEK,
    });

    // 2. Data Extractor Lambda
    const dataExtractorFunction = new lambda.DockerImageFunction(this, 'DataExtractorFunction', {
      functionName: `${projectName}-data-extractor`,
      code: lambda.DockerImageCode.fromImageAsset(path.join(__dirname, '../lambda/data-extractor')),
      timeout: cdk.Duration.minutes(15),
      memorySize: 2048,
      role: lambdaRole,
      environment: {
        DATA_BUCKET: dataBucket.bucketName,
        BEDROCK_MODEL_ID: bedrockModelId,
      },
      logRetention: logs.RetentionDays.ONE_WEEK,
    });

    // 3. Entity Extractor Lambda
    const entityExtractorFunction = new lambda.DockerImageFunction(this, 'EntityExtractorFunction', {
      functionName: `${projectName}-entity-extractor`,
      code: lambda.DockerImageCode.fromImageAsset(path.join(__dirname, '../lambda/entity-extractor')),
      timeout: cdk.Duration.minutes(15),
      memorySize: 2048,
      role: lambdaRole,
      environment: {
        DATA_BUCKET: dataBucket.bucketName,
        BEDROCK_MODEL_ID: bedrockModelId,
      },
      logRetention: logs.RetentionDays.ONE_WEEK,
    });

    // 4. Neptune Loader Lambda
    const neptuneLoaderFunction = new lambda.DockerImageFunction(this, 'NeptuneLoaderFunction', {
      functionName: `${projectName}-neptune-loader`,
      code: lambda.DockerImageCode.fromImageAsset(path.join(__dirname, '../lambda/neptune-loader')),
      timeout: cdk.Duration.minutes(15),
      memorySize: 1024,
      role: lambdaRole,
      vpc,
      vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS },
      securityGroups: [neptuneSecurityGroup],
      environment: {
        DATA_BUCKET: dataBucket.bucketName,
        NEPTUNE_ENDPOINT: neptuneCluster.attrEndpoint,
        NEPTUNE_PORT: '8182',
      },
      logRetention: logs.RetentionDays.ONE_WEEK,
    });

    // 5. Chat Handler Lambda
    const chatHandlerFunction = new lambda.DockerImageFunction(this, 'ChatHandlerFunction', {
      functionName: `${projectName}-chat-handler`,
      code: lambda.DockerImageCode.fromImageAsset(path.join(__dirname, '../lambda/chat-handler')),
      timeout: cdk.Duration.seconds(30),
      memorySize: 1024,
      role: lambdaRole,
      vpc,
      vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS },
      securityGroups: [neptuneSecurityGroup],
      environment: {
        NEPTUNE_ENDPOINT: neptuneCluster.attrEndpoint,
        NEPTUNE_PORT: '8182',
        BEDROCK_MODEL_ID: bedrockModelId,
      },
      logRetention: logs.RetentionDays.ONE_WEEK,
    });

    // ========================================
    // Step Functions State Machine
    // ========================================

    // Define tasks
    const collectImagesTask = new tasks.LambdaInvoke(this, 'CollectImages', {
      lambdaFunction: imageCollectorFunction,
      outputPath: '$.Payload',
    });

    const extractDataTask = new tasks.LambdaInvoke(this, 'ExtractData', {
      lambdaFunction: dataExtractorFunction,
      outputPath: '$.Payload',
    });

    const extractEntitiesTask = new tasks.LambdaInvoke(this, 'ExtractEntities', {
      lambdaFunction: entityExtractorFunction,
      outputPath: '$.Payload',
    });

    const loadToNeptuneTask = new tasks.LambdaInvoke(this, 'LoadToNeptune', {
      lambdaFunction: neptuneLoaderFunction,
      outputPath: '$.Payload',
    });

    // Define workflow
    const definition = collectImagesTask
      .next(extractDataTask)
      .next(extractEntitiesTask)
      .next(loadToNeptuneTask);

    const stateMachine = new stepfunctions.StateMachine(this, 'PipelineStateMachine', {
      stateMachineName: `${projectName}-pipeline`,
      definition,
      timeout: cdk.Duration.hours(2),
      logs: {
        destination: new logs.LogGroup(this, 'StateMachineLogGroup', {
          logGroupName: `/aws/stepfunctions/${projectName}-pipeline`,
          retention: logs.RetentionDays.ONE_WEEK,
          removalPolicy: cdk.RemovalPolicy.DESTROY,
        }),
        level: stepfunctions.LogLevel.ALL,
      },
    });

    // ========================================
    // API Gateway for Chat UI
    // ========================================
    const api = new apigateway.RestApi(this, 'ChatAPI', {
      restApiName: `${projectName}-chat-api`,
      description: 'API for historical newspaper chat interface',
      defaultCorsPreflightOptions: {
        allowOrigins: apigateway.Cors.ALL_ORIGINS,
        allowMethods: apigateway.Cors.ALL_METHODS,
        allowHeaders: ['Content-Type', 'Authorization'],
      },
    });

    const chatIntegration = new apigateway.LambdaIntegration(chatHandlerFunction);
    const chatResource = api.root.addResource('chat');
    chatResource.addMethod('POST', chatIntegration);

    const healthResource = api.root.addResource('health');
    healthResource.addMethod('GET', chatIntegration);

    // ========================================
    // Outputs
    // ========================================
    new cdk.CfnOutput(this, 'DataBucketName', {
      value: dataBucket.bucketName,
      description: 'S3 bucket for pipeline data',
      exportName: `${projectName}-data-bucket`,
    });

    new cdk.CfnOutput(this, 'StateMachineArn', {
      value: stateMachine.stateMachineArn,
      description: 'Step Functions state machine ARN',
      exportName: `${projectName}-state-machine-arn`,
    });

    new cdk.CfnOutput(this, 'NeptuneEndpoint', {
      value: neptuneCluster.attrEndpoint,
      description: 'Neptune cluster endpoint',
      exportName: `${projectName}-neptune-endpoint`,
    });

    new cdk.CfnOutput(this, 'APIGatewayURL', {
      value: api.url,
      description: 'API Gateway URL for chat interface',
      exportName: `${projectName}-api-url`,
    });

    new cdk.CfnOutput(this, 'ChatEndpoint', {
      value: `${api.url}chat`,
      description: 'Chat endpoint URL',
    });
  }
}
