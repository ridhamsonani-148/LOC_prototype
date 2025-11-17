#!/usr/bin/env bash
set -euo pipefail

echo "========================================="
echo "Chronicling America Pipeline Quick Start"
echo "========================================="
echo ""

# Check prerequisites
echo "Checking prerequisites..."

# Check AWS CLI
if ! command -v aws &> /dev/null; then
    echo "❌ AWS CLI not found. Please install: https://aws.amazon.com/cli/"
    exit 1
fi
echo "✅ AWS CLI installed"

# Check Node.js
if ! command -v node &> /dev/null; then
    echo "❌ Node.js not found. Please install: https://nodejs.org/"
    exit 1
fi
echo "✅ Node.js installed"

# Check CDK
if ! command -v cdk &> /dev/null; then
    echo "⚠️  AWS CDK not found. Installing..."
    npm install -g aws-cdk@2.161.1
fi
echo "✅ AWS CDK installed"

# Check AWS credentials
if ! aws sts get-caller-identity &> /dev/null; then
    echo "❌ AWS credentials not configured. Run: aws configure"
    exit 1
fi
echo "✅ AWS credentials configured"

echo ""
echo "All prerequisites met!"
echo ""

# Install dependencies
echo "Installing dependencies..."
npm install
echo "✅ Dependencies installed"
echo ""

# Build TypeScript
echo "Building TypeScript..."
npm run build
echo "✅ Build complete"
echo ""

# Bootstrap CDK
echo "Bootstrapping CDK..."
cdk bootstrap
echo "✅ CDK bootstrapped"
echo ""

# Deploy
echo "========================================="
echo "Ready to deploy!"
echo "========================================="
echo ""
echo "Run one of the following commands:"
echo ""
echo "1. Automated deployment (recommended):"
echo "   ./deploy.sh"
echo ""
echo "2. Manual CDK deployment:"
echo "   cdk deploy ChroniclingAmericaStack"
echo ""
echo "3. View what will be deployed:"
echo "   cdk synth"
echo ""

exit 0
