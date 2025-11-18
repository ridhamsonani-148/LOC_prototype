import * as cdk from "aws-cdk-lib";
import * as lambda from "aws-cdk-lib/aws-lambda";
import * as s3 from "aws-cdk-lib/aws-s3";
import * as iam from "aws-cdk-lib/aws-iam";
import * as ec2 from "aws-cdk-lib/aws-ec2";
import * as neptune from "aws-cdk-lib/aws-neptune";
import * as apigateway from "aws-cdk-lib/aws-apigateway";
import * as stepfunctions from "aws-cdk-lib/aws-stepfunctions";
import * as tasks from "aws-cdk-lib/aws-stepfunctions-tasks";
import * as logs from "aws-cdk-lib/aws-logs";
import * as cr from "aws-cdk-lib/custom-resources";
import { Construct } from "constructs";
import * as path from "path";

export interface ChroniclingAmericaStackProps extends cdk.StackProps {
  projectName: string;
  dataBucketName?: string;
  bedrockModelId?: string;
}

export class ChroniclingAmericaStack extends cdk.Stack {
  constructor(
    scope: Construct,
    id: string,
    props: ChroniclingAmericaStackProps
  ) {
    super(scope, id, props);

    const projectName = props.projectName;
    const bedrockModelId =
      props.bedrockModelId || "anthropic.claude-3-5-sonnet-20241022-v2:0";

    // ========================================
    // S3 Bucket for Data Storage
    // ========================================
    const dataBucket = new s3.Bucket(this, "DataBucket", {
      bucketName:
        props.dataBucketName ||
        `${projectName}-data-${this.account}-${this.region}`,
      encryption: s3.BucketEncryption.S3_MANAGED,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      removalPolicy: cdk.RemovalPolicy.RETAIN,
      lifecycleRules: [
        {
          id: "DeleteOldExtractions",
          expiration: cdk.Duration.days(90),
          prefix: "extracted/",
        },
      ],
    });

    // ========================================
    // VPC for Neptune
    // ========================================
    const vpc = new ec2.Vpc(this, "NeptuneVPC", {
      maxAzs: 2,
      natGateways: 1,
      subnetConfiguration: [
        {
          cidrMask: 24,
          name: "Public",
          subnetType: ec2.SubnetType.PUBLIC,
        },
        {
          cidrMask: 24,
          name: "Private",
          subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS,
        },
        {
          cidrMask: 28,
          name: "Isolated",
          subnetType: ec2.SubnetType.PRIVATE_ISOLATED,
        },
      ],
    });

    // Security Group for Neptune
    const neptuneSecurityGroup = new ec2.SecurityGroup(
      this,
      "NeptuneSecurityGroup",
      {
        vpc,
        description: "Security group for Neptune cluster",
        allowAllOutbound: true,
      }
    );

    neptuneSecurityGroup.addIngressRule(
      neptuneSecurityGroup,
      ec2.Port.tcp(8182),
      "Allow Neptune access from within security group"
    );

    // ========================================
    // Neptune Cluster
    // ========================================
    const neptuneSubnetGroup = new neptune.CfnDBSubnetGroup(
      this,
      "NeptuneSubnetGroup",
      {
        dbSubnetGroupDescription: "Subnet group for Neptune cluster",
        subnetIds: vpc.isolatedSubnets.map((subnet) => subnet.subnetId),
        dbSubnetGroupName: `${projectName}-neptune-subnet-group`,
      }
    );

    const neptuneCluster = new neptune.CfnDBCluster(this, "NeptuneCluster", {
      dbClusterIdentifier: `${projectName}-neptune-cluster`,
      dbSubnetGroupName: neptuneSubnetGroup.dbSubnetGroupName,
      vpcSecurityGroupIds: [neptuneSecurityGroup.securityGroupId],
      iamAuthEnabled: false,
      storageEncrypted: true,
    });

    neptuneCluster.addDependency(neptuneSubnetGroup);

    const neptuneInstance = new neptune.CfnDBInstance(this, "NeptuneInstance", {
      dbInstanceClass: "db.t3.medium",
      dbClusterIdentifier: neptuneCluster.dbClusterIdentifier,
      dbInstanceIdentifier: `${projectName}-neptune-instance`,
    });

    neptuneInstance.addDependency(neptuneCluster);

    // ========================================
    // Lambda Execution Role
    // ========================================
    const lambdaRole = new iam.Role(this, "LambdaExecutionRole", {
      assumedBy: new iam.ServicePrincipal("lambda.amazonaws.com"),
      managedPolicies: [
        iam.ManagedPolicy.fromAwsManagedPolicyName(
          "service-role/AWSLambdaVPCAccessExecutionRole"
        ),
        iam.ManagedPolicy.fromAwsManagedPolicyName(
          "service-role/AWSLambdaBasicExecutionRole"
        ),
      ],
    });

    // Grant S3 permissions
    dataBucket.grantReadWrite(lambdaRole);

    // Grant Bedrock permissions
    lambdaRole.addToPolicy(
      new iam.PolicyStatement({
        effect: iam.Effect.ALLOW,
        actions: [
          "bedrock:InvokeModel",
          "bedrock:InvokeModelWithResponseStream",
        ],
        resources: [
          `arn:aws:bedrock:${this.region}::foundation-model/*`,
          `arn:aws:bedrock:*::foundation-model/*`,
          `arn:aws:bedrock:${this.region}:${this.account}:inference-profile/*`,
          `arn:aws:bedrock:*:${this.account}:inference-profile/*`,
        ],
      })
    );

    // Grant AWS Marketplace permissions for Bedrock Marketplace models
    lambdaRole.addToPolicy(
      new iam.PolicyStatement({
        effect: iam.Effect.ALLOW,
        actions: [
          "aws-marketplace:ViewSubscriptions",
          "aws-marketplace:Subscribe",
        ],
        resources: ["*"],
      })
    );

    // Grant Neptune permissions
    lambdaRole.addToPolicy(
      new iam.PolicyStatement({
        effect: iam.Effect.ALLOW,
        actions: ["neptune-db:*"],
        resources: ["*"],
      })
    );

    // ========================================
    // Lambda Functions (Docker-based)
    // ========================================

    // 1. Image Collector Lambda
    const imageCollectorLogGroup = new logs.LogGroup(
      this,
      "ImageCollectorLogGroup",
      {
        logGroupName: `/aws/lambda/${projectName}-image-collector`,
        retention: logs.RetentionDays.ONE_WEEK,
        removalPolicy: cdk.RemovalPolicy.DESTROY,
      }
    );

    const imageCollectorFunction = new lambda.DockerImageFunction(
      this,
      "ImageCollectorFunction",
      {
        functionName: `${projectName}-image-collector`,
        code: lambda.DockerImageCode.fromImageAsset(
          path.join(__dirname, "../lambda/image-collector")
        ),
        timeout: cdk.Duration.minutes(15),
        memorySize: 1024,
        role: lambdaRole,
        environment: {
          DATA_BUCKET: dataBucket.bucketName,
        },
        logGroup: imageCollectorLogGroup,
      }
    );

    // 2. Image to PDF Lambda
    const imageToPdfLogGroup = new logs.LogGroup(this, "ImageToPdfLogGroup", {
      logGroupName: `/aws/lambda/${projectName}-image-to-pdf`,
      retention: logs.RetentionDays.ONE_WEEK,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    const imageToPdfFunction = new lambda.DockerImageFunction(
      this,
      "ImageToPdfFunction",
      {
        functionName: `${projectName}-image-to-pdf`,
        code: lambda.DockerImageCode.fromImageAsset(
          path.join(__dirname, "../lambda/image-to-pdf")
        ),
        timeout: cdk.Duration.minutes(15),
        memorySize: 3008,
        role: lambdaRole,
        environment: {
          DATA_BUCKET: dataBucket.bucketName,
        },
        logGroup: imageToPdfLogGroup,
      }
    );

    // 3. Bedrock Data Automation Lambda
    const bedrockDataAutomationLogGroup = new logs.LogGroup(
      this,
      "BedrockDataAutomationLogGroup",
      {
        logGroupName: `/aws/lambda/${projectName}-bedrock-data-automation`,
        retention: logs.RetentionDays.ONE_WEEK,
        removalPolicy: cdk.RemovalPolicy.DESTROY,
      }
    );

    const bedrockDataAutomationFunction = new lambda.DockerImageFunction(
      this,
      "BedrockDataAutomationFunction",
      {
        functionName: `${projectName}-bedrock-data-automation`,
        code: lambda.DockerImageCode.fromImageAsset(
          path.join(__dirname, "../lambda/bedrock-data-automation")
        ),
        timeout: cdk.Duration.minutes(15),
        memorySize: 2048,
        role: lambdaRole,
        environment: {
          DATA_BUCKET: dataBucket.bucketName,
          AWS_ACCOUNT_ID: this.account,
          BEDROCK_REGION: this.region,
          LOG_LEVEL: "INFO",
          // Using a different project name to avoid ghost project conflict
          BEDROCK_PROJECT_NAME: "chronicling-america-pipeline",
        },
        logGroup: bedrockDataAutomationLogGroup,
      }
    );

    // Grant Bedrock Data Automation permissions
    lambdaRole.addToPolicy(
      new iam.PolicyStatement({
        effect: iam.Effect.ALLOW,
        actions: [
          "bedrock:ListDataAutomationProjects",
          "bedrock:CreateDataAutomationProject",
          "bedrock:GetDataAutomationProject",
          "bedrock:UpdateDataAutomationProject",
          "bedrock:DeleteDataAutomationProject",
          "bedrock:CreateBlueprint",
          "bedrock:GetBlueprint",
          "bedrock:ListBlueprints",
        ],
        resources: ["*"],
      })
    );

    // Grant Bedrock Data Automation Runtime permissions
    lambdaRole.addToPolicy(
      new iam.PolicyStatement({
        effect: iam.Effect.ALLOW,
        actions: [
          "bedrock-data-automation-runtime:InvokeDataAutomationAsync",
          "bedrock-data-automation-runtime:GetDataAutomationStatus",
        ],
        resources: ["*"],
      })
    );

    // Grant permission to use AWS-managed Bedrock Data Automation Profiles
    // These profiles are owned by AWS (account 803633136603) and require explicit permission
    lambdaRole.addToPolicy(
      new iam.PolicyStatement({
        effect: iam.Effect.ALLOW,
        actions: [
          "bedrock:InvokeDataAutomationAsync",
          "bedrock:GetDataAutomationStatus",
          "bedrock:GetDataAutomationProfile",
          "bedrock:ListDataAutomationProfiles",
        ],
        resources: [
          // Own account's projects
          `arn:aws:bedrock:${this.region}:${this.account}:data-automation-project/*`,
        ],
      })
    );

    // Grant Bedrock model invocation permissions (required by Data Automation)
    lambdaRole.addToPolicy(
      new iam.PolicyStatement({
        effect: iam.Effect.ALLOW,
        actions: [
          "bedrock:InvokeModel",
          "bedrock:InvokeModelWithResponseStream",
        ],
        resources: [
          `arn:aws:bedrock:${this.region}::foundation-model/*`,
          `arn:aws:bedrock:*::foundation-model/*`,
        ],
      })
    );

    // 4. Data Extractor Lambda (kept for compatibility)
    const dataExtractorLogGroup = new logs.LogGroup(
      this,
      "DataExtractorLogGroup",
      {
        logGroupName: `/aws/lambda/${projectName}-data-extractor`,
        retention: logs.RetentionDays.ONE_WEEK,
        removalPolicy: cdk.RemovalPolicy.DESTROY,
      }
    );

    const dataExtractorFunction = new lambda.DockerImageFunction(
      this,
      "DataExtractorFunction",
      {
        functionName: `${projectName}-data-extractor`,
        code: lambda.DockerImageCode.fromImageAsset(
          path.join(__dirname, "../lambda/data-extractor")
        ),
        timeout: cdk.Duration.minutes(15),
        memorySize: 2048,
        role: lambdaRole,
        environment: {
          DATA_BUCKET: dataBucket.bucketName,
          BEDROCK_MODEL_ID: bedrockModelId,
        },
        logGroup: dataExtractorLogGroup,
      }
    );

    // 3. Entity Extractor Lambda
    const entityExtractorLogGroup = new logs.LogGroup(
      this,
      "EntityExtractorLogGroup",
      {
        logGroupName: `/aws/lambda/${projectName}-entity-extractor`,
        retention: logs.RetentionDays.ONE_WEEK,
        removalPolicy: cdk.RemovalPolicy.DESTROY,
      }
    );

    const entityExtractorFunction = new lambda.DockerImageFunction(
      this,
      "EntityExtractorFunction",
      {
        functionName: `${projectName}-entity-extractor`,
        code: lambda.DockerImageCode.fromImageAsset(
          path.join(__dirname, "../lambda/entity-extractor")
        ),
        timeout: cdk.Duration.minutes(15),
        memorySize: 2048,
        role: lambdaRole,
        environment: {
          DATA_BUCKET: dataBucket.bucketName,
          BEDROCK_MODEL_ID: bedrockModelId,
        },
        logGroup: entityExtractorLogGroup,
      }
    );

    // 4. Neptune Loader Lambda
    const neptuneLoaderLogGroup = new logs.LogGroup(
      this,
      "NeptuneLoaderLogGroup",
      {
        logGroupName: `/aws/lambda/${projectName}-neptune-loader`,
        retention: logs.RetentionDays.ONE_WEEK,
        removalPolicy: cdk.RemovalPolicy.DESTROY,
      }
    );

    const neptuneLoaderFunction = new lambda.DockerImageFunction(
      this,
      "NeptuneLoaderFunction",
      {
        functionName: `${projectName}-neptune-loader`,
        code: lambda.DockerImageCode.fromImageAsset(
          path.join(__dirname, "../lambda/neptune-loader")
        ),
        timeout: cdk.Duration.minutes(15),
        memorySize: 1024,
        role: lambdaRole,
        vpc,
        vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS },
        securityGroups: [neptuneSecurityGroup],
        environment: {
          DATA_BUCKET: dataBucket.bucketName,
          NEPTUNE_ENDPOINT: neptuneCluster.attrEndpoint,
          NEPTUNE_PORT: "8182",
        },
        logGroup: neptuneLoaderLogGroup,
      }
    );

    // 5. Chat Handler Lambda
    const chatHandlerLogGroup = new logs.LogGroup(this, "ChatHandlerLogGroup", {
      logGroupName: `/aws/lambda/${projectName}-chat-handler`,
      retention: logs.RetentionDays.ONE_WEEK,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    const chatHandlerFunction = new lambda.DockerImageFunction(
      this,
      "ChatHandlerFunction",
      {
        functionName: `${projectName}-chat-handler`,
        code: lambda.DockerImageCode.fromImageAsset(
          path.join(__dirname, "../lambda/chat-handler")
        ),
        timeout: cdk.Duration.seconds(30),
        memorySize: 1024,
        role: lambdaRole,
        vpc,
        vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS },
        securityGroups: [neptuneSecurityGroup],
        environment: {
          NEPTUNE_ENDPOINT: neptuneCluster.attrEndpoint,
          NEPTUNE_PORT: "8182",
          BEDROCK_MODEL_ID: bedrockModelId,
        },
        logGroup: chatHandlerLogGroup,
      }
    );

    // ========================================
    // Step Functions State Machine
    // ========================================

    // Define tasks
    const collectImagesTask = new tasks.LambdaInvoke(this, "CollectImages", {
      lambdaFunction: imageCollectorFunction,
      outputPath: "$.Payload",
    });

    const imageToPdfTask = new tasks.LambdaInvoke(this, "ImageToPdf", {
      lambdaFunction: imageToPdfFunction,
      outputPath: "$.Payload",
    });

    const bedrockDataAutomationTask = new tasks.LambdaInvoke(
      this,
      "BedrockDataAutomation",
      {
        lambdaFunction: bedrockDataAutomationFunction,
        outputPath: "$.Payload",
      }
    );

    const extractEntitiesTask = new tasks.LambdaInvoke(
      this,
      "ExtractEntities",
      {
        lambdaFunction: entityExtractorFunction,
        outputPath: "$.Payload",
      }
    );

    const loadToNeptuneTask = new tasks.LambdaInvoke(this, "LoadToNeptune", {
      lambdaFunction: neptuneLoaderFunction,
      outputPath: "$.Payload",
    });

    // Define workflow: Images → PDF → Bedrock Data Automation → Entities → Neptune
    const definition = collectImagesTask
      .next(imageToPdfTask)
      .next(bedrockDataAutomationTask)
      .next(extractEntitiesTask)
      .next(loadToNeptuneTask);

    const stateMachine = new stepfunctions.StateMachine(
      this,
      "PipelineStateMachine",
      {
        stateMachineName: `${projectName}-pipeline`,
        definitionBody: stepfunctions.DefinitionBody.fromChainable(definition),
        timeout: cdk.Duration.hours(2),
        logs: {
          destination: new logs.LogGroup(this, "StateMachineLogGroup", {
            logGroupName: `/aws/stepfunctions/${projectName}-pipeline`,
            retention: logs.RetentionDays.ONE_WEEK,
            removalPolicy: cdk.RemovalPolicy.DESTROY,
          }),
          level: stepfunctions.LogLevel.ALL,
        },
      }
    );

    // ========================================
    // API Gateway for Chat UI
    // ========================================
    const api = new apigateway.RestApi(this, "ChatAPI", {
      restApiName: `${projectName}-chat-api`,
      description: "API for historical newspaper chat interface",
      defaultCorsPreflightOptions: {
        allowOrigins: apigateway.Cors.ALL_ORIGINS,
        allowMethods: apigateway.Cors.ALL_METHODS,
        allowHeaders: ["Content-Type", "Authorization"],
      },
    });

    const chatIntegration = new apigateway.LambdaIntegration(
      chatHandlerFunction
    );
    const chatResource = api.root.addResource("chat");
    chatResource.addMethod("POST", chatIntegration);

    const healthResource = api.root.addResource("health");
    healthResource.addMethod("GET", chatIntegration);

    // ========================================
    // Outputs
    // ========================================
    new cdk.CfnOutput(this, "DataBucketName", {
      value: dataBucket.bucketName,
      description: "S3 bucket for pipeline data",
      exportName: `${projectName}-data-bucket`,
    });

    new cdk.CfnOutput(this, "StateMachineArn", {
      value: stateMachine.stateMachineArn,
      description: "Step Functions state machine ARN",
      exportName: `${projectName}-state-machine-arn`,
    });

    new cdk.CfnOutput(this, "NeptuneEndpoint", {
      value: neptuneCluster.attrEndpoint,
      description: "Neptune cluster endpoint",
      exportName: `${projectName}-neptune-endpoint`,
    });

    new cdk.CfnOutput(this, "APIGatewayURL", {
      value: api.url,
      description: "API Gateway URL for chat interface",
      exportName: `${projectName}-api-url`,
    });

    new cdk.CfnOutput(this, "ChatEndpoint", {
      value: `${api.url}chat`,
      description: "Chat endpoint URL",
    });

    // ========================================
    // Auto-Start Pipeline After Deployment (Optional)
    // ========================================
    // Uncomment to automatically trigger pipeline after each deployment
    /*
    const autoStartPipeline = new cr.AwsCustomResource(this, 'AutoStartPipeline', {
      onCreate: {
        service: 'StepFunctions',
        action: 'startExecution',
        parameters: {
          stateMachineArn: stateMachine.stateMachineArn,
          input: JSON.stringify({
            start_date: '1815-08-01',
            end_date: '1815-08-31',
            max_pages: 10
          })
        },
        physicalResourceId: cr.PhysicalResourceId.of(Date.now().toString()),
      },
      policy: cr.AwsCustomResourcePolicy.fromStatements([
        new iam.PolicyStatement({
          actions: ['states:StartExecution'],
          resources: [stateMachine.stateMachineArn],
        }),
      ]),
    });
    */
  }
}
