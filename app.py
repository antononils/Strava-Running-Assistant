from flask import Flask, redirect, request, jsonify, render_template
from openai import OpenAI
import os, requests, atexit, time, tempfile
from dotenv import load_dotenv

# Import project functions
from functions.strava_api import _load_tokens, _save_tokens, _auth_url, get_strava_activity, get_strava_activities
from functions.strava_activities import filter_activities, generate_route
from functions.map_funcs import build_empty_map, build_polyline_route_map, build_single_route_map, _cleanup_map_file
from functions.llm_funcs import llm_with_response_schema, llm_general_chat, llm_analyze_activity, RouterOptions, RouteInfo, GenerateRouteInfo, transcribe_audio
from functions.llm_prompts import ROUTER_PROMPT, RUN_INFO_PROMPT, GENERATE_RUN_PROMPT, SUMMARIZE_OPTIONS_PROMPT, GENERAL_CHAT_PROMPT, ACTIVITY_ANALYSIS_PROMPT
from functions.rag_funcs import rag_ranking


# ----- Setup -----
load_dotenv()
app = Flask(__name__)

# LLM client
CLIENT = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Strava API setup
STRAVA_CLIENT_ID = os.getenv("STRAVA_CLIENT_ID")
STRAVA_CLIENT_SECRET = os.getenv("STRAVA_CLIENT_SECRET")
REDIRECT_URI = os.getenv("STRAVA_REDIRECT_URI", "http://localhost:5000/callback")

# File paths
TOKEN_FILE = "tokens.json"
MAP_PATH = "static/map.html"

# Make sure map file is cleaned when app stops
atexit.register(_cleanup_map_file)
build_empty_map(MAP_PATH)

# Keep history of conversation
HISTORY = []
MAX_HISTORY = 20

# Helper: add message to memory and keep it short
def _append_history(role, content):
    """Store chat history so LLM can keep context."""
    HISTORY.append({"role": role, "content": content})
    if len(HISTORY) > MAX_HISTORY:
        del HISTORY[: len(HISTORY) - MAX_HISTORY]


# ----- Routes -----

@app.route("/")
def home():
    """Show landing page or redirect to login if not connected to Strava."""
    if not _load_tokens(TOKEN_FILE):
        return redirect("/login")
    global HISTORY
    HISTORY.clear()
    return render_template("index.html")


@app.route("/login")
def login():
    """Send user to Strava login page for authorization."""
    return redirect(_auth_url(STRAVA_CLIENT_ID, REDIRECT_URI))


@app.route("/callback")
def callback():
    """Handle Strava login and save access tokens."""
    code = request.args.get("code")
    if not code:
        return "Missing 'code' from Strava.", 400
    
    # Exchange the code for access tokens
    r = requests.post(
        "https://www.strava.com/oauth/token",
        data={
            "client_id": STRAVA_CLIENT_ID,
            "client_secret": STRAVA_CLIENT_SECRET,
            "code": code,
            "grant_type": "authorization_code"
        },
        timeout=20
    )
    r.raise_for_status()
    _save_tokens(r.json(), TOKEN_FILE)
    return redirect("/")


@app.route("/api/chat", methods=["POST"])
def chat():
    """Main chat endpoint that decides if user wants a run or general chat."""
    if not _load_tokens(TOKEN_FILE):
        return jsonify({"error": "Please login with Strava first."}), 401
    
    data = request.get_json(silent=True) or {}
    user_input = (data.get("message") or "").strip()
    if not user_input:
        return jsonify({"error": "Missing 'message' in request."}), 400
    
    # Build conversation history for LLM
    msgs = HISTORY.copy()
    msgs.append({"role": "user", "content": user_input})

    # Ask model if user is talking about a run
    start = time.time()
    route_decision = llm_with_response_schema(CLIENT, msgs, RouterOptions, ROUTER_PROMPT)
    print(f"Route: {time.time() - start:.2f} seconds")

    if route_decision.get("suggest_run"):
        # Get run details (distance, city etc.)
        start = time.time()
        route_info = llm_with_response_schema(CLIENT, msgs, RouteInfo, RUN_INFO_PROMPT)
        print(f"Extraction: {time.time() - start:.2f} seconds")
        msgs.append({"role": "assistant", "content": str(route_info)})
        print(route_info)

        # Fetch and filter user activities from Strava
        start = time.time()
        strava_activities = get_strava_activities(200, TOKEN_FILE, STRAVA_CLIENT_ID, STRAVA_CLIENT_SECRET)
        activities = filter_activities(strava_activities, route_info)
        filtered_activities = []
        for activity in activities:
            map_data = (activity.get("map") or {})
            polyline_str = map_data.get("summary_polyline") or map_data.get("polyline")
            filtered_activities.append({
                "route_id": f"strava-{activity.get('id')}", "kind": "strava", "id": activity.get("id"), "name": activity.get("name"), 
                "distance": activity.get("distance"), "moving_time": activity.get("moving_time"), 
                "total_elevation_gain": activity.get("total_elevation_gain"), "average_speed": activity.get("average_speed"),
                "average_heartrate": activity.get("average_heartrate"), "start_date": activity.get("start_date"), "polyline": polyline_str
            })
        print(f"Filtering: {time.time() - start:.2f} seconds")
        
        # RAG filtering and sorting
        start = time.time()
        rag_activities = rag_ranking(CLIENT, user_input, filtered_activities)
        print(f"RAG: {time.time() - start:.2f} seconds")
        
        # Summary via LLM
        summary_copy = [{k: v for k, v in a.items() if k != "polyline"} for a in rag_activities]
        summary_input = msgs + [{"role": "assistant", "content": str(summary_copy)}]
        start = time.time()
        summary = llm_general_chat(CLIENT, summary_input, SUMMARIZE_OPTIONS_PROMPT)
        print(f"Summary: {time.time() - start:.2f} seconds")

        # Pick the first route to show by default
        auto_select_route_id = None
        if rag_activities:
            auto_select_route_id = rag_activities[0]["route_id"]

        # Add interaction to history
        _append_history("user", user_input)
        _append_history("assistant", summary)

        # Send back to frontend
        return jsonify({
            "input": user_input, "mode": "run", "run_details": route_info, "count": len(rag_activities), "results": rag_activities,
            "auto_select_route_id": auto_select_route_id, "response": summary, "map": f"/{MAP_PATH}"
        })
    
    elif route_decision.get("generate_new_route"):
        # Get run details (distance, city etc.)
        start = time.time()
        route_info = llm_with_response_schema(CLIENT, msgs, GenerateRouteInfo, GENERATE_RUN_PROMPT)
        print(f"Extract: {time.time() - start:.2f} seconds")
        msgs.append({"role": "assistant", "content": str(route_info)})
    
        # Generate new route
        start = time.time()
        route_id = f"gen-{int(time.time()*1000)}"
        coords = generate_route(route_info)
        activities = [{
            "route_id": route_id, "kind": "generated", "name": "Generated Route", "distance": route_info.get("distance"), 
            "start_city": route_info.get("city"), "coords": coords
        }]
        print(f"Generation: {time.time() - start:.2f} seconds")

        # Create a short summary for the user
        summary_text = f"Generated a ~{int(route_info.get('distance', 0) or 0)} m loop in {route_info.get('city','unknown')}."

        # Save message and response to chat history
        _append_history("user", user_input)
        _append_history("assistant", summary_text)

        # Send back route info to frontend
        return jsonify({
            "input": user_input, "mode": "run", "run_details": route_info, "count": 1, "results": activities,
            "auto_select_route_id": route_id, "response": summary_text, "map": f"/{MAP_PATH}"
        })
    
    else:
        # If message was not about a specific run, do normal chat
        start = time.time()
        chat_response = llm_general_chat(CLIENT, msgs, GENERAL_CHAT_PROMPT)
        print(f"Chat: {time.time() - start:.2f} seconds")

        # Save question and answer to history
        _append_history("user", user_input)
        _append_history("assistant", chat_response)
        
        # Send normal chat reply
        return jsonify({"input": user_input, "mode": "chat", "response": chat_response})


@app.route("/api/select_route", methods=["POST"])
def select_route():
    """Show one selected route on the map."""
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip() or "Route"
    coords = data.get("coords")
    polyline = data.get("polyline")

    # Draw generated route (lat/lon list)
    if coords and isinstance(coords, list):
        build_single_route_map(coords, name, MAP_PATH)
        return jsonify({"ok": True})

    # Draw Strava route from encoded polyline
    if polyline:
        build_polyline_route_map(polyline, name, MAP_PATH)
        return jsonify({"ok": True})

    # If no route data, reset map
    build_empty_map(MAP_PATH)
    return jsonify({"ok": True, "empty": True})


@app.route("/api/clear_route", methods=["POST"])
def clear_route():
    """Reset map to default empty state."""
    build_empty_map(MAP_PATH)
    return jsonify({"ok": True})


@app.route("/api/analyze_activity", methods=["POST"])
def analyze_activity():
    """Send selected activity to LLM for analysis."""
    data = request.get_json(silent=True) or {}
    kind = (data.get("kind") or "").strip()

    # Get map screenshot from frontend
    image_data_url = data.get("image_data_url")

    try:
        # Create text input for LLM depending on route type
        if kind == "strava":
            route_id = data.get("id")
            activity = get_strava_activity(route_id, TOKEN_FILE, STRAVA_CLIENT_ID, STRAVA_CLIENT_SECRET)
            text_blob = f"Strava activity full JSON follows. Name: {activity.get('name')}\n\n" + str(activity)
        elif kind == "generated":
            coords = data.get("coords") or []
            distance = data.get("distance")
            text_blob = f"Generated route. Distance (m): {distance}. No Strava stats available.\nCoordinates (first 50):\n{coords[:50]}"
        else:
            return jsonify({"ok": False, "error": "Unknown kind"}), 400

        # Ask LLM for analysis
        analysis = llm_analyze_activity(CLIENT, text_blob, image_data_url, ACTIVITY_ANALYSIS_PROMPT)
        return jsonify({"ok": True, "analysis": analysis})
    
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/transcribe", methods=["POST"])
def transcribe():
    """Receive an audio blob, run Whisper, return text."""
    file = request.files.get("file")
    if not file:
        return jsonify({"error": "Missing 'file' in form-data."}), 400

    # Save to a temp path
    fd, tmp_path = tempfile.mkstemp(suffix=".webm")
    os.close(fd)
    file.save(tmp_path)
    try:
        text = transcribe_audio(CLIENT, tmp_path) or ""
        return jsonify({"text": text})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        try:
            os.remove(tmp_path)
        except Exception:
            pass


if __name__ == "__main__":
    app.run(debug=True)