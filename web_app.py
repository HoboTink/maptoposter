"""
Flask web application for Map Poster Generator.
Provides a browser-based GUI to create map posters.
"""

# Set matplotlib backend before any imports that use it
import matplotlib
matplotlib.use('Agg')

from flask import Flask, render_template, jsonify, request, send_from_directory
import threading
import uuid
import os
import json
import traceback

# Import functions from existing poster generator
import create_map_poster as poster

app = Flask(__name__)

# Job tracking storage
jobs = {}

# Lock for thread-safe job updates
jobs_lock = threading.Lock()


def update_job_status(job_id, status, progress=None, result=None, error=None):
    """Thread-safe job status update."""
    with jobs_lock:
        if job_id in jobs:
            jobs[job_id]['status'] = status
            if progress is not None:
                jobs[job_id]['progress'] = progress
            if result is not None:
                jobs[job_id]['result'] = result
            if error is not None:
                jobs[job_id]['error'] = error


def run_generation(job_id, city, country, theme_name, distance, display_name):
    """
    Background task to generate a poster.
    Updates job status as it progresses.
    """
    try:
        # Step 1: Geocoding
        update_job_status(job_id, 'geocoding', progress=10)
        coords = poster.get_coordinates(city, country)

        # Step 2: Load theme and set global
        update_job_status(job_id, 'loading_theme', progress=20)
        poster.THEME = poster.load_theme(theme_name)

        # Step 3: Downloading map data
        update_job_status(job_id, 'downloading', progress=30)

        # Generate output filename
        filename_city = display_name if display_name else city
        output_file = poster.generate_output_filename(filename_city, theme_name)

        # Step 4: Rendering
        update_job_status(job_id, 'rendering', progress=50)
        poster.create_poster(city, country, coords, distance, output_file, display_name)

        # Step 5: Complete
        # Extract just the filename from the path
        filename = os.path.basename(output_file)
        update_job_status(job_id, 'complete', progress=100, result=filename)

    except Exception as e:
        error_msg = str(e)
        traceback.print_exc()
        update_job_status(job_id, 'error', error=error_msg)


@app.route('/')
def index():
    """Serve the main HTML page."""
    return render_template('index.html')


@app.route('/api/themes')
def get_themes():
    """Return list of available themes with their colors."""
    themes = []
    theme_names = poster.get_available_themes()

    for theme_name in theme_names:
        theme_path = os.path.join(poster.THEMES_DIR, f"{theme_name}.json")
        try:
            with open(theme_path, 'r') as f:
                theme_data = json.load(f)
                themes.append({
                    'id': theme_name,
                    'name': theme_data.get('name', theme_name),
                    'description': theme_data.get('description', ''),
                    'bg': theme_data.get('bg', '#FFFFFF'),
                    'text': theme_data.get('text', '#000000'),
                    'road_primary': theme_data.get('road_primary', '#333333'),
                    'road_secondary': theme_data.get('road_secondary', '#666666'),
                })
        except Exception as e:
            print(f"Error loading theme {theme_name}: {e}")

    return jsonify(themes)


@app.route('/api/generate', methods=['POST'])
def generate():
    """Start poster generation in background thread."""
    data = request.json

    # Validate required fields
    city = data.get('city', '').strip()
    country = data.get('country', '').strip()

    if not city or not country:
        return jsonify({'error': 'City and country are required'}), 400

    theme_name = data.get('theme', 'feature_based')
    distance = data.get('distance', 10000)
    display_name = data.get('display_name', '').strip() or None

    # Validate theme exists
    available_themes = poster.get_available_themes()
    if theme_name not in available_themes:
        return jsonify({'error': f"Theme '{theme_name}' not found"}), 400

    # Validate distance
    try:
        distance = int(distance)
        if distance < 1000 or distance > 50000:
            return jsonify({'error': 'Distance must be between 1000 and 50000 meters'}), 400
    except ValueError:
        return jsonify({'error': 'Invalid distance value'}), 400

    # Create job
    job_id = str(uuid.uuid4())
    with jobs_lock:
        jobs[job_id] = {
            'status': 'pending',
            'progress': 0,
            'result': None,
            'error': None,
            'params': {
                'city': city,
                'country': country,
                'theme': theme_name,
                'distance': distance,
                'display_name': display_name
            }
        }

    # Start background thread
    thread = threading.Thread(
        target=run_generation,
        args=(job_id, city, country, theme_name, distance, display_name)
    )
    thread.daemon = True
    thread.start()

    return jsonify({'job_id': job_id})


@app.route('/api/status/<job_id>')
def get_status(job_id):
    """Check generation progress."""
    with jobs_lock:
        if job_id not in jobs:
            return jsonify({'error': 'Job not found'}), 404

        job = jobs[job_id].copy()

    return jsonify(job)


@app.route('/posters/<filename>')
def serve_poster(filename):
    """Serve generated poster images."""
    posters_dir = os.path.abspath(poster.POSTERS_DIR)
    return send_from_directory(posters_dir, filename)


if __name__ == '__main__':
    # Ensure directories exist
    os.makedirs(poster.POSTERS_DIR, exist_ok=True)
    os.makedirs('templates', exist_ok=True)
    os.makedirs('static', exist_ok=True)

    print("=" * 50)
    print("Map Poster Generator - Web Interface")
    print("=" * 50)
    print("Starting server at http://localhost:5001")
    print("Press Ctrl+C to stop")
    print("=" * 50)

    app.run(debug=True, host='0.0.0.0', port=5001)
