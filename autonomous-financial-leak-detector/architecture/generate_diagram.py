from diagrams import Diagram, Cluster, Edge
from diagrams.aws.storage import S3
from diagrams.aws.compute import Lambda
from diagrams.aws.ml import Sagemaker
from diagrams.aws.integration import SNS, SQS
from diagrams.aws.management import Cloudwatch
from diagrams.aws.general import User
from diagrams.onprem.client import Client

with Diagram(
    "Autonomous Financial Leak Detector",
    filename="architecture/afld_architecture",
    outformat="png",
    show=False,
    direction="LR",
    graph_attr={"fontsize": "14", "bgcolor": "#f9f9f9", "pad": "0.8"},
):
    fintech_app = Client("Fintech App /\nPayment Gateway")

    with Cluster("AWS — us-east-2"):

        with Cluster("Ingestion"):
            landing = S3("S3 Landing\nafld-transactions-landing-*")

        with Cluster("AI Processing"):
            auditor = Lambda("Lambda Auditor\nPython 3.12 · 512MB")
            bedrock = Sagemaker("Amazon Bedrock\nClaude 3.5 Sonnet")

        with Cluster("Storage"):
            reports = S3("S3 Audit Reports\nafld-audit-reports-*")

        with Cluster("Alerting"):
            sns = SNS("SNS\naudit-alerts")
            alerts_q = SQS("SQS\nalerts-queue")
            dlq = SQS("SQS DLQ\nfailed events")

        with Cluster("Observability"):
            cw = Cloudwatch("CloudWatch\nLogs · Alarms")

    team = User("Ops Team\n(Email / Slack)")

    # Flow
    fintech_app >> Edge(label="PUT transaction.json") >> landing
    landing >> Edge(label="S3 Event Trigger") >> auditor
    auditor >> Edge(label="InvokeModel") >> bedrock
    bedrock >> Edge(label="AuditResult JSON") >> auditor
    auditor >> Edge(label="save report") >> reports
    auditor >> Edge(label="Publish alert") >> sns
    sns >> alerts_q
    sns >> team
    auditor >> Edge(label="on failure", style="dashed", color="red") >> dlq
    auditor >> Edge(label="logs + metrics", style="dashed", color="gray") >> cw
    cw >> Edge(label="alarm → SNS", style="dashed", color="orange") >> sns
