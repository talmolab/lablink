import gzip
import json
import base64
import os
import urllib3

API_ENDPOINT = os.environ.get("API_ENDPOINT")
http = urllib3.PoolManager()


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

    print(f"Sending payload to {API_ENDPOINT}: {payload}")
    try:
        # Send logs to external API
        response = http.request(
            "POST",
            API_ENDPOINT,
            body=json.dumps(payload),
            headers={"Content-Type": "application/json"},
        )
        print("Response status:", response.status)
        print("Response data:", response.data.decode())
        if response.status != 200:
            raise RuntimeError(f"API error {response.status}: {response.data}")
        print("Successfully sent logs to API")
    except urllib3.exceptions.HTTPError as e:
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