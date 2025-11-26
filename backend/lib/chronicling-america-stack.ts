import * as cdk from "aws-cdk-lib";
import * as lambda from "aws-cdk-lib/aws-lambda";
import * as s3 from "aws-cdk-lib/aws-s3";
import * as s3n from "aws-cdk-lib/aws-s3-notifications";
import * as iam from "aws-cdk-lib/aws-iam";
import * as apigateway from "aws-cdk-lib/aws-apigateway";
import * as logs from "aws-cdk-lib/aws-logs";
import * as ecs from "aws-cdk-lib/aws-ecs";
import * as ecr from "aws-cdk-lib/aws-ecr";
import * as ec2 from "aws-cdk-lib/aws-ec2";
import * as bedrock from "aws-cdk-lib/aws-bedrock";
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
      eventBridgeEnabled: true, // Enable EventBridge for S3 events
    });

    // Grant Bedrock service access to S3 bucket
    dataBucket.addToResourcePolicy(
      new iam.PolicyStatement({
        effect: iam.Effect.ALLOW,
        principals: [new iam.ServicePrincipal("bedrock.amazonaws.com")],
        actions: ["s3:GetObject", "s3:ListBucket"],
        resources: [dataBucket.bucketArn, `${dataBucket.bucketArn}/*`],
        conditions: {
          StringEquals: {
            "aws:SourceAccount": this.account,
          },
        },
      })
    );

    // ========================================
    // VPC for Fargate (minimal setup)
    // ========================================
    const vpc = new ec2.Vpc(this, "VPC", {
      maxAzs: 2,
      natGateways: 0, // Use public subnets only for cost savings
      subnetConfiguration: [
        {
          cidrMask: 24,
          name: "Public",
          subnetType: ec2.SubnetType.PUBLIC,
        },
      ],
      restrictDefaultSecurityGroup: false, // Disable to avoid IAM permission issues
    });

    // ========================================
    // ECS Cluster for Fargate Tasks
    // ========================================
    const ecsCluster = new ecs.Cluster(this, "ECSCluster", {
      clusterName: `${projectName}-cluster`,
      vpc,
      containerInsights: true,
    });

    // ECR Repository for Fargate task image
    const collectorRepository = new ecr.Repository(
      this,
      "CollectorRepository",
      {
        repositoryName: `${projectName}-collector`,
        removalPolicy: cdk.RemovalPolicy.RETAIN,
        lifecycleRules: [
          {
            maxImageCount: 5,
            description: "Keep only 5 most recent images",
          },
        ],
      }
    );

    // Fargate Task Execution Role
    const fargateExecutionRole = new iam.Role(this, "FargateExecutionRole", {
      assumedBy: new iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
      managedPolicies: [
        iam.ManagedPolicy.fromAwsManagedPolicyName(
          "service-role/AmazonECSTaskExecutionRolePolicy"
        ),
      ],
    });

    // Fargate Task Role (for application permissions)
    const fargateTaskRole = new iam.Role(this, "FargateTaskRole", {
      assumedBy: new iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
    });

    // Grant S3 permissions to Fargate task
    dataBucket.grantReadWrite(fargateTaskRole);

    // Fargate Task Definition
    const collectorTaskDefinition = new ecs.FargateTaskDefinition(
      this,
      "CollectorTaskDefinition",
      {
        family: `${projectName}-collector`,
        cpu: 2048, // 2 vCPU
        memoryLimitMiB: 4096, // 4 GB
        executionRole: fargateExecutionRole,
        taskRole: fargateTaskRole,
      }
    );

    // Log Group for Fargate task
    const collectorLogGroup = new logs.LogGroup(this, "CollectorLogGroup", {
      logGroupName: `/ecs/${projectName}-collector`,
      retention: logs.RetentionDays.ONE_WEEK,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    // Container Definition
    collectorTaskDefinition.addContainer("CollectorContainer", {
      containerName: "collector",
      image: ecs.ContainerImage.fromEcrRepository(
        collectorRepository,
        "latest"
      ),
      logging: ecs.LogDrivers.awsLogs({
        streamPrefix: "collector",
        logGroup: collectorLogGroup,
      }),
      environment: {
        BUCKET_NAME: dataBucket.bucketName,
        START_CONGRESS: "1",
        END_CONGRESS: "16",
        BILL_TYPES: "hr,s",
        CONGRESS_API_KEY: "MThtRT5WkFu8I8CHOfiLLebG4nsnKcX3JnNv2N8A",
      },
    });

    // ========================================
    // IAM Role for Bedrock Knowledge Base
    // ========================================
    const knowledgeBaseRole = new iam.Role(this, "KnowledgeBaseRole", {
      assumedBy: new iam.ServicePrincipal("bedrock.amazonaws.com"),
      description: "Role for Bedrock Knowledge Base to access S3 and Neptune",
    });

    // Grant S3 read permissions
    dataBucket.grantRead(knowledgeBaseRole);

    // Grant Neptune Analytics permissions
    knowledgeBaseRole.addToPolicy(
      new iam.PolicyStatement({
        effect: iam.Effect.ALLOW,
        actions: ["neptune-graph:*", "neptune-db:*"],
        resources: ["*"],
      })
    );

    // Grant Bedrock model access
    knowledgeBaseRole.addToPolicy(
      new iam.PolicyStatement({
        effect: iam.Effect.ALLOW,
        actions: ["bedrock:InvokeModel"],
        resources: [
          `arn:aws:bedrock:${this.region}::foundation-model/amazon.titan-embed-text-v2:0`,
        ],
      })
    );

    // ========================================
    // Custom Resource Lambda for Automated KB Setup
    // ========================================
    const kbSetupRole = new iam.Role(this, "KBSetupRole", {
      assumedBy: new iam.ServicePrincipal("lambda.amazonaws.com"),
      managedPolicies: [
        iam.ManagedPolicy.fromAwsManagedPolicyName(
          "service-role/AWSLambdaBasicExecutionRole"
        ),
      ],
    });

    // Grant permissions to create Neptune Analytics graph
    kbSetupRole.addToPolicy(
      new iam.PolicyStatement({
        effect: iam.Effect.ALLOW,
        actions: [
          "neptune-graph:CreateGraph",
          "neptune-graph:DeleteGraph",
          "neptune-graph:GetGraph",
          "neptune-graph:ListGraphs",
        ],
        resources: ["*"],
      })
    );

    // Grant permissions to create Bedrock Knowledge Base
    kbSetupRole.addToPolicy(
      new iam.PolicyStatement({
        effect: iam.Effect.ALLOW,
        actions: [
          "bedrock:CreateKnowledgeBase",
          "bedrock:DeleteKnowledgeBase",
          "bedrock:GetKnowledgeBase",
          "bedrock:CreateDataSource",
          "bedrock:DeleteDataSource",
          "bedrock:GetDataSource",
        ],
        resources: ["*"],
      })
    );

    // Grant PassRole for Knowledge Base role
    kbSetupRole.addToPolicy(
      new iam.PolicyStatement({
        effect: iam.Effect.ALLOW,
        actions: ["iam:PassRole"],
        resources: [knowledgeBaseRole.roleArn],
      })
    );

    const kbSetupFunction = new lambda.DockerImageFunction(
      this,
      "KBSetupFunction",
      {
        functionName: `${projectName}-kb-setup`,
        code: lambda.DockerImageCode.fromImageAsset(
          path.join(__dirname, "../lambda/kb-setup")
        ),
        timeout: cdk.Duration.minutes(15),
        memorySize: 512,
        role: kbSetupRole,
      }
    );

    // Custom Resource to Create KB Automatically
    const kbSetupProvider = new cr.Provider(this, "KBSetupProvider", {
      onEventHandler: kbSetupFunction,
    });

    const kbSetup = new cdk.CustomResource(this, "KBSetup", {
      serviceToken: kbSetupProvider.serviceToken,
      properties: {
        ProjectName: projectName,
        BucketArn: dataBucket.bucketArn,
        RoleArn: knowledgeBaseRole.roleArn,
        Region: this.region,
        AccountId: this.account,
      },
    });

    // Get KB attributes (these will be available after KB creation)
    const knowledgeBaseId = kbSetup.getAttString("KnowledgeBaseId");
    const dataSourceId = kbSetup.getAttString("DataSourceId");
    const graphId = kbSetup.getAttString("GraphId");

    // ========================================
    // Lambda Execution Role
    // ========================================
    const lambdaRole = new iam.Role(this, "LambdaExecutionRole", {
      assumedBy: new iam.ServicePrincipal("lambda.amazonaws.com"),
      managedPolicies: [
        iam.ManagedPolicy.fromAwsManagedPolicyName(
          "service-role/AWSLambdaBasicExecutionRole"
        ),
      ],
    });

    // Grant ECS permissions to Lambda (for Fargate trigger)
    lambdaRole.addToPolicy(
      new iam.PolicyStatement({
        effect: iam.Effect.ALLOW,
        actions: ["ecs:RunTask", "ecs:DescribeTasks", "ecs:StopTask"],
        resources: ["*"],
      })
    );

    // Grant PassRole for ECS task execution
    lambdaRole.addToPolicy(
      new iam.PolicyStatement({
        effect: iam.Effect.ALLOW,
        actions: ["iam:PassRole"],
        resources: [fargateExecutionRole.roleArn, fargateTaskRole.roleArn],
      })
    );

    // Grant Bedrock Agent permissions (for KB sync)
    lambdaRole.addToPolicy(
      new iam.PolicyStatement({
        effect: iam.Effect.ALLOW,
        actions: [
          "bedrock:StartIngestionJob",
          "bedrock:GetIngestionJob",
          "bedrock:ListIngestionJobs",
        ],
        resources: ["*"],
      })
    );

    // Grant Bedrock model invocation permissions (for chat)
    lambdaRole.addToPolicy(
      new iam.PolicyStatement({
        effect: iam.Effect.ALLOW,
        actions: [
          "bedrock:InvokeModel",
          "bedrock:Retrieve",
          "bedrock:RetrieveAndGenerate",
        ],
        resources: ["*"],
      })
    );

    // ========================================
    // Lambda Functions (Only 3 needed!)
    // ========================================

    // 1. Fargate Trigger Lambda
    const fargateTriggerLogGroup = new logs.LogGroup(
      this,
      "FargateTriggerLogGroup",
      {
        logGroupName: `/aws/lambda/${projectName}-fargate-trigger`,
        retention: logs.RetentionDays.ONE_WEEK,
        removalPolicy: cdk.RemovalPolicy.DESTROY,
      }
    );

    const fargateTriggerFunction = new lambda.DockerImageFunction(
      this,
      "FargateTriggerFunction",
      {
        functionName: `${projectName}-fargate-trigger`,
        code: lambda.DockerImageCode.fromImageAsset(
          path.join(__dirname, "../lambda/fargate-trigger")
        ),
        timeout: cdk.Duration.seconds(30),
        memorySize: 256,
        role: lambdaRole,
        environment: {
          ECS_CLUSTER_NAME: ecsCluster.clusterName,
          TASK_DEFINITION_ARN: collectorTaskDefinition.taskDefinitionArn,
          SUBNET_IDS: vpc.publicSubnets.map((s) => s.subnetId).join(","),
          BUCKET_NAME: dataBucket.bucketName,
          START_CONGRESS: "1",
          END_CONGRESS: "16",
          BILL_TYPES: "hr,s",
        },
        logGroup: fargateTriggerLogGroup,
      }
    );

    // 2. KB Sync Trigger Lambda
    const kbSyncTriggerLogGroup = new logs.LogGroup(
      this,
      "KBSyncTriggerLogGroup",
      {
        logGroupName: `/aws/lambda/${projectName}-kb-sync-trigger`,
        retention: logs.RetentionDays.ONE_WEEK,
        removalPolicy: cdk.RemovalPolicy.DESTROY,
      }
    );

    const kbSyncTriggerFunction = new lambda.DockerImageFunction(
      this,
      "KBSyncTriggerFunction",
      {
        functionName: `${projectName}-kb-sync-trigger`,
        code: lambda.DockerImageCode.fromImageAsset(
          path.join(__dirname, "../lambda/kb-sync-trigger")
        ),
        timeout: cdk.Duration.minutes(2),
        memorySize: 256,
        role: lambdaRole,
        environment: {
          KNOWLEDGE_BASE_ID: knowledgeBaseId,
          DATA_SOURCE_ID: dataSourceId,
        },
        logGroup: kbSyncTriggerLogGroup,
      }
    );

    // Ensure KB sync trigger is created after KB setup completes
    kbSyncTriggerFunction.node.addDependency(kbSetup);

    // Add S3 event notification to trigger KB sync when files are added
    dataBucket.addEventNotification(
      s3.EventType.OBJECT_CREATED,
      new s3n.LambdaDestination(kbSyncTriggerFunction),
      { prefix: "extracted/", suffix: ".txt" }
    );

    // 3. Chat Handler Lambda
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
        environment: {
          KNOWLEDGE_BASE_ID: knowledgeBaseId,
          MODEL_ID: bedrockModelId,
        },
        logGroup: chatHandlerLogGroup,
      }
    );

    // Ensure chat handler is created after KB setup completes
    chatHandlerFunction.node.addDependency(kbSetup);

    // ========================================
    // API Gateway for Chat UI
    // ========================================
    const api = new apigateway.RestApi(this, "ChatAPI", {
      restApiName: `${projectName}-chat-api`,
      description: "API for historical Congress bills chat interface",
      defaultCorsPreflightOptions: {
        allowOrigins: apigateway.Cors.ALL_ORIGINS,
        allowMethods: apigateway.Cors.ALL_METHODS,
        allowHeaders: ["Content-Type", "Authorization"],
      },
    });

    // Chat endpoint
    const chatIntegration = new apigateway.LambdaIntegration(
      chatHandlerFunction
    );
    const chatResource = api.root.addResource("chat");
    chatResource.addMethod("POST", chatIntegration);

    // Health endpoint
    const healthResource = api.root.addResource("health");
    healthResource.addMethod("GET", chatIntegration);

    // Fargate trigger endpoint
    const collectIntegration = new apigateway.LambdaIntegration(
      fargateTriggerFunction
    );
    const collectResource = api.root.addResource("collect");
    collectResource.addMethod("POST", collectIntegration);

    // ========================================
    // Outputs
    // ========================================
    new cdk.CfnOutput(this, "DataBucketName", {
      value: dataBucket.bucketName,
      description: "S3 bucket for pipeline data",
      exportName: `${projectName}-data-bucket`,
    });

    new cdk.CfnOutput(this, "KnowledgeBaseId", {
      value: knowledgeBaseId,
      description: "Bedrock Knowledge Base ID (auto-created)",
      exportName: `${projectName}-kb-id`,
    });

    new cdk.CfnOutput(this, "DataSourceId", {
      value: dataSourceId,
      description: "Bedrock Data Source ID (auto-created)",
      exportName: `${projectName}-ds-id`,
    });

    new cdk.CfnOutput(this, "NeptuneGraphId", {
      value: graphId,
      description: "Neptune Analytics Graph ID (auto-created)",
      exportName: `${projectName}-graph-id`,
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

    new cdk.CfnOutput(this, "CollectEndpoint", {
      value: `${api.url}collect`,
      description: "Fargate collection trigger endpoint",
    });

    new cdk.CfnOutput(this, "ECRRepositoryUri", {
      value: collectorRepository.repositoryUri,
      description: "ECR repository URI for Fargate collector image",
      exportName: `${projectName}-ecr-repository`,
    });

    new cdk.CfnOutput(this, "FargateTaskDefinitionArn", {
      value: collectorTaskDefinition.taskDefinitionArn,
      description: "Fargate task definition ARN",
      exportName: `${projectName}-fargate-task`,
    });

    new cdk.CfnOutput(this, "KBSetupStatus", {
      value: "Knowledge Base created automatically via Custom Resource",
      description: "KB setup status",
    });

    new cdk.CfnOutput(this, "ExtractedDataPrefix", {
      value: `s3://${dataBucket.bucketName}/extracted/`,
      description: "S3 prefix where Fargate saves extracted bill text",
    });

    new cdk.CfnOutput(this, "BedrockModelId", {
      value: bedrockModelId,
      description: "Bedrock model ID used for chat responses",
    });
  }
}
