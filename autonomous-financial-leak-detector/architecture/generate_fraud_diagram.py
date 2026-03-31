"""
generate_fraud_diagram.py
Architecture diagram for Derecho Viejo — Real-Time Fraud Detection Stack.
Uses: diagrams (Graphviz-based), AWS + custom icons.
Run: python architecture/generate_fraud_diagram.py
Output: architecture/derecho_viejo_architecture.png
"""
from diagrams import Diagram, Cluster, Edge
from diagrams.aws.analytics import KinesisDataStreams, ManagedStreamingForKafka
from diagrams.aws.compute import Lambda
from diagrams.aws.integration import SNS
from diagrams.aws.management import Cloudwatch
from diagrams.aws.general import User
from diagrams.aws.storage import S3
from diagrams.custom import Custom

GRAPH = {
    "fontsize":  "13",
    "bgcolor":   "#0d1117",
    "fontcolor": "#e6edf3",
    "pad":       "1.2",
    "splines":   "curved",
    "nodesep":   "0.8",
    "ranksep":   "1.2",
}

CLUSTER_STYLE = {
    "bgcolor":    "#161b22",
    "fontcolor":  "#58a6ff",
    "fontsize":   "12",
    "style":      "rounded",
    "pencolor":   "#30363d",
}

EDGE_MAIN  = {"color": "#58a6ff", "style": "bold"}
EDGE_ALERT = {"color": "#f85149", "style": "dashed"}
EDGE_OBS   = {"color": "#3fb950", "style": "dashed"}

with Diagram(
    "Derecho Viejo - Real-Time Fraud Detection",
    filename="architecture/derecho_viejo_architecture",
    outformat="png",
    show=False,
    direction="LR",
    graph_attr=GRAPH,
):
    producer = User("Transaction\nProducer")

    with Cluster("AWS — us-east-2", graph_attr=CLUSTER_STYLE):

        with Cluster("Ingestion", graph_attr=CLUSTER_STYLE):
            kinesis = KinesisDataStreams("Kinesis\nON_DEMAND")

        with Cluster("Stateful Processing", graph_attr=CLUSTER_STYLE):
            flink = ManagedStreamingForKafka("Managed Flink\nParallelism=2\nCheckpoint 60s")
            checkpoints = S3("S3\nCheckpoints")

        with Cluster("AI Inference", graph_attr=CLUSTER_STYLE):
            scorer = Lambda("fraud_scorer\nPython 3.12 · 512MB")
            bedrock = Lambda("Amazon Bedrock\nClaude 3 Haiku\n(On-Demand)")

        with Cluster("Alerting & Observability", graph_attr=CLUSTER_STYLE):
            sns_fraud   = SNS("SNS\nfraud-alerts")
            cw          = Cloudwatch("CloudWatch\nAlarms · Logs")

    ops = User("Ops Team\n(Email Alert)")

    # ── Main flow ──────────────────────────────────────────────────────────────
    producer  >> Edge(**EDGE_MAIN, label="PUT tx")    >> kinesis
    kinesis   >> Edge(**EDGE_MAIN)                    >> flink
    flink     >> Edge(**EDGE_MAIN, label="Invoke")    >> scorer
    scorer    >> Edge(**EDGE_MAIN, label="InvokeModel") >> bedrock
    bedrock   >> Edge(**EDGE_MAIN, label="verdict")   >> scorer
    flink     >> Edge(**EDGE_OBS,  label="checkpoint") >> checkpoints

    # ── Alerts ─────────────────────────────────────────────────────────────────
    scorer    >> Edge(**EDGE_ALERT, label="FRAUD/SUSPICIOUS") >> sns_fraud
    sns_fraud >> Edge(**EDGE_ALERT)                           >> ops

    # ── Observability ──────────────────────────────────────────────────────────
    scorer    >> Edge(**EDGE_OBS, label="logs/metrics") >> cw
    flink     >> Edge(**EDGE_OBS)                       >> cw
    cw        >> Edge(**EDGE_ALERT, label="$15 alarm")  >> sns_fraud
