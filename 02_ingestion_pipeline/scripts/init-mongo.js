// MongoDB init script for local/container runtime.
// Creates the collections required by the ingestion pipeline.
// MongoDB creates _id as ObjectId automatically for inserted documents.

const databaseName = "etl_pipeline_db";
const database = db.getSiblingDB(databaseName);

const requiredCollections = [
  "file_collection",
  "processing_results",
];

for (const collectionName of requiredCollections) {
  if (!database.getCollectionNames().includes(collectionName)) {
    database.createCollection(collectionName);
    print(`Created collection ${databaseName}.${collectionName}`);
  } else {
    print(`Collection ${databaseName}.${collectionName} already exists`);
  }
}

print(`MongoDB init completed for ${databaseName}`);
