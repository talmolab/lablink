import gzip
import json
import base64


def lambda_handler(event, context):
    data = event["awslogs"]["data"]
    decoded = gzip.decompress(base64.b64decode(data))
    log_events = json.loads(decoded)
    print("Log events:", log_events)
