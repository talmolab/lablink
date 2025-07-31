import gzip
import json
import base64
import os
import requests

API_ENDPOINT = os.environ.get("API_ENDPOINT")


def lambda_handler(event, context):
    data = event["awslogs"]["data"]
    decoded = gzip.decompress(base64.b64decode(data))
    log_events = json.loads(decoded)
    print("Log events:", log_events)

    # Extract metadata
    log_group = log_events.get("logGroup")
    log_stream = log_events.get("logStream")
    log_messages = [e["message"] for e in log_events.get("logEvents", [])]

    # Generate payload for API
    payload = {
        "log_group": log_group,
        "log_stream": log_stream,
        "messages": log_messages,
    }

    try:
        # Send logs to external API
        response = requests.post(API_ENDPOINT, json=payload)
        response.raise_for_status()
        print("Successfully sent logs to API")
    except requests.exceptions.RequestException as e:
        print(f"Error sending logs to API: {e}")
        raise e

    return {
        "statusCode": 200,
        "body": json.dumps(
            {
                "message": "Logs processed successfully",
                "log_group": log_group,
                "log_stream": log_stream,
                "log_count": len(log_messages),
            }
        ),
    }
