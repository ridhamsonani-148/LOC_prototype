# Deployment Fix - Variable Declaration Order

## Issue Fixed

Build was failing with:
```
error TS2448: Block-scoped variable 'lambdaRole' used before its declaration.
error TS2454: Variable 'lambdaRole' is used before being assigned.
```

## Root Cause

The Neptune Exporter and KB Sync Trigger Lambda functions were being created **before** the `lambdaRole` variable was declared, but they needed to reference it.

## Solution

Moved the Lambda function declarations to the correct order:

### Before (Broken)
```typescript
// Line 160: Neptune Exporter tries to use lambdaRole
const neptuneExporterFunction = new lambda.DockerImageFunction(..., {
  role: lambdaRole,  // ❌ Error: lambdaRole not declared yet
});

// Line 400: KB Sync Trigger tries to use lambdaRole  
const kbSyncTriggerFunction = new lambda.DockerImageFunction(..., {
  role: lambdaRole,  // ❌ Error: lambdaRole not declared yet
});

// Line 431: lambdaRole finally declared
const lambdaRole = new iam.Role(...);
```

### After (Fixed)
```typescript
// Line 160: Bedrock Knowledge Base setup (doesn't need lambdaRole)
const knowledgeBase = new bedrock.CfnKnowledgeBase(...);

// Line 431: lambdaRole declared
const lambdaRole = new iam.Role(...);

// Line 670: Neptune Exporter now uses lambdaRole
const neptuneExporterFunction = new lambda.DockerImageFunction(..., {
  role: lambdaRole,  // ✅ Works: lambdaRole already declared
});

// Line 710: KB Sync Trigger now uses lambdaRole
const kbSyncTriggerFunction = new lambda.DockerImageFunction(..., {
  role: lambdaRole,  // ✅ Works: lambdaRole already declared
});
```

## Files Changed

- `backend/lib/chronicling-america-stack.ts`
  - Moved Neptune Exporter Lambda creation to after lambdaRole declaration
  - Moved KB Sync Trigger Lambda creation to after lambdaRole declaration
  - Kept Bedrock Knowledge Base setup before lambdaRole (doesn't need it)

## Verification

Build should now succeed:
```bash
cd backend
npm run build
```

## Deployment

Now you can deploy successfully:
```bash
cd backend
./deploy.sh
```

The automated pipeline will work as designed:
1. ✅ Creates all infrastructure
2. ✅ Creates Bedrock Knowledge Base automatically
3. ✅ Creates Neptune Exporter Lambda
4. ✅ Creates KB Sync Trigger Lambda
5. ✅ Configures Step Functions pipeline with all steps
