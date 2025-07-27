import azure.functions as func
import logging
from azure.cosmos import CosmosClient, PartitionKey
from datetime import datetime, timezone
import os

# Create an Azure Function app with anonymous access
app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)

# These are retrieved from environment variables (from local.settings.json or Azure App Settings)
# For the purpose of this project, we assume the Azure Cosmos DB emulator is running locally
COSMOS_URL = os.getenv("COSMOS_URL")
COSMOS_KEY = os.getenv("COSMOS_KEY")
DATABASE_NAME = os.getenv("COSMOS_DB_NAME", "SensorDB")
CONTAINER_NAME = os.getenv("COSMOS_CONTAINER_NAME", "Readings")

# Create DB/container if they don't already exist — useful for local development
client = CosmosClient(COSMOS_URL, COSMOS_KEY)
database = client.create_database_if_not_exists(id=DATABASE_NAME)
container = database.create_container_if_not_exists(
    id=CONTAINER_NAME,
    partition_key=PartitionKey(path="/sensorId")
)

@app.route(route="update-sensors", methods=["POST"])
def update_sensors(req: func.HttpRequest) -> func.HttpResponse:
    try:
        data = req.get_json()

        # Payload must be a non-empty list with max of 100 items (to avoid abuse or large batch problems)
        if not isinstance(data, list) or len(data) == 0 or len(data) > 100:
            return func.HttpResponse("Invalid payload: Must be a list of 1 to 100 items", status_code=400)

        for item in data:
            # Each item must include a sensorId (used as document ID and partition key)
            if "sensorId" not in item:
                continue  # Skip items without sensorId

            sensor_id = item["sensorId"]
            try:
                # If found, we update only fields that are provided (non-destructive update)
                existing_doc = container.read_item(item=sensor_id, partition_key=sensor_id)
                for k, v in item.items():
                    if v is not None:
                        existing_doc[k] = v  # Update field if value is present
                # Add/update timestamp to reflect the update time
                existing_doc["updatedAt"] = datetime.now(timezone.utc).isoformat()
                # Replace the item in the container
                container.replace_item(item=existing_doc, body=existing_doc)
            except Exception:
                # If the item doesn't exist (or a race condition occurs), we create a new one
                item["id"] = sensor_id
                item["createdAt"] = datetime.now(timezone.utc).isoformat()
                container.upsert_item(item)

        return func.HttpResponse("Sensor data processed", status_code=200)

    except ValueError:
        # If request body is not valid JSON
        return func.HttpResponse("Invalid JSON format", status_code=400)
    except Exception as e:
        # Catch-all for unexpected errors; log and return 500 error
        logging.exception("Unhandled error")
        return func.HttpResponse(f"Server error: {str(e)}", status_code=500)
