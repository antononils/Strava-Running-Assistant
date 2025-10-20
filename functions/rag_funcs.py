import pandas as pd
import numpy as np
from datetime import datetime
import platform


# Helper to format ISO timestamp into date and time strings
def _format_datetime(iso_str):
    """Convert ISO time to readable date and time."""
    dt = datetime.strptime(iso_str, "%Y-%m-%dT%H:%M:%SZ")
    day_format = "%-d" if platform.system() != "Windows" else "%#d"
    date_str = dt.strftime(f"{day_format} %B %Y")
    time_str = dt.strftime("%H:%M")
    return date_str, time_str

# Helper to convert one Strava activity row to a short text description
def _row_to_text(row):
    """Describe an activity as text for embeddings."""
    date_str, time_str = _format_datetime(row['start_date'])
    return (
        f"Distance {row['distance'] / 1000:.2f} km, "
        f"elevation gain {row['total_elevation_gain'] / 1000:.2f} m, "
        f"moving time {row['moving_time'] / 60:.2f} min, "
        f"pace {1 / row['average_speed'] * 50 / 3:.2f} min/km, "
        f"heart rate {row['average_heartrate']:.2f} bpm, "
        f"date {date_str}, "
        f"time of day {time_str}."
    )

# Compare query embedding with activity embeddings and return top matches
def find_best_match(client, df, query, embeddings, top_k=5):
    """Return top matching activities based on cosine similarity."""
    q_resp = client.embeddings.create(model="text-embedding-3-small", input=query)
    query_vec = np.array(q_resp.data[0].embedding, dtype=np.float32)
    
    # Normalize vectors and compute cosine similarity
    denom = (np.linalg.norm(embeddings, axis=1) * np.linalg.norm(query_vec) + 1e-8)
    scores = (embeddings @ query_vec) / denom
    
    # Sort by similarity score, highest first
    best_idx = np.argsort(scores)[::-1] #[:top_k]
    return df.iloc[best_idx], scores

# Main RAG ranking function used in route selection
def rag_ranking(client, query, activities):
    """Rank Strava activities by relevance to the user query."""
    if len(activities) == 0:
        return activities
    
    # Convert activities to DataFrame
    df = pd.DataFrame.from_records(activities)

    # Create natural-language descriptions for embeddings
    texts = [_row_to_text(row) for _, row in df.iterrows()]
    
    # Generate embeddings for each activity
    response = client.embeddings.create(model="text-embedding-3-small", input=texts)
    embeddings = np.array([d.embedding for d in response.data])
    
    # Find the most similar activities to the user query
    results, scores = find_best_match(client, df, query, embeddings)

    # Return reordered list of activities as dicts
    return df.iloc[results.index].to_dict('records')