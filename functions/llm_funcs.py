from pydantic import BaseModel


# Define response schema for routing user intent
class RouterOptions(BaseModel):
    enable_chat: bool
    suggest_run: bool
    generate_new_route: bool

# Define schema for run details for suggestions
class RouteInfo(BaseModel):
    distance: float
    elevation_gain: float
    time: float
    pace: float
    heart_rate: int
    city: str

# Define schema for run details for generating new route
class GenerateRouteInfo(BaseModel):
    distance: float
    city: str


# Generate model output following a specific JSON schema
def llm_with_response_schema(client, user_input, response_schema, system_instructions):
    """Call LLM with a schema and return structured JSON."""
    response = client.responses.parse(
        model='gpt-4o',
        instructions=system_instructions,
        input=user_input,
        text_format=response_schema,
        temperature=0
    )
    return response.output_parsed.model_dump()

# General chat without schema (normal conversation)
def llm_general_chat(client, user_input, system_instructions):
    """Call LLM for general chat or summary."""
    response = client.responses.create(
        model='gpt-4o',
        instructions=system_instructions,
        input=user_input,
        temperature=0
    )
    return response.output_text

# Analyze an activity (with map image)
def llm_analyze_activity(client, text_blob, image_url, system_instructions):
    """Send text (and image) to LLM for analysis."""
    parts = [{"role": "user", "content": [{"type": "input_image", "image_url": image_url}]}]

    # Send both to the model
    response = client.responses.create(
        model='gpt-4o',
        instructions=system_instructions,
        input=parts,
        temperature=0
    )
    return response.output_text

# Audio transcription to allow speech inpu
def transcribe_audio(client, audio_path):
    """ Transcribe an audio file using OpenAI Whisper."""
    with open(audio_path, "rb") as f:
        response = client.audio.transcriptions.create(
            model="whisper-1",
            file=f,
            prompt="Transcribe this user request in english."
        )
    return response.text or ""