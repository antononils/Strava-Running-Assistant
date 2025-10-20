import os, folium
from pathlib import Path


# Decode a Google/Strava encoded polyline string into [(lat, lon), ...]
def _decode_polyline(polyline_str):
    """Convert an encoded polyline string into a list of coordinates."""
    coords, index, lat, lng = [], 0, 0, 0
    while index < len(polyline_str):
        # Decode latitude and longitude alternately
        for coord in (lat, lng):
            shift = result = 0
            while True:
                # Read one character, subtract 63 (as per encoding spec)
                b = ord(polyline_str[index]) - 63
                index += 1

                # Add lower 5 bits to result, shifted appropriately
                result |= (b & 0x1f) << shift
                shift += 5

                # If continuation bit not set, stop reading this number
                if b < 0x20:
                    break
            
            # Decode sign and value    
            dcoord = ~(result >> 1) if (result & 1) else (result >> 1)

            # Update lat or lon
            if coord is lat:
                lat += dcoord
                coord = lat
            else:
                lng += dcoord
                coord = lng

        # Append decoded coordinate pair, scaled down to degrees
        coords.append((lat / 1e5, lng / 1e5))
    return coords

# Helper to inject JS that allows map to be exported as PNG
def _inject_exporter(html_path):
    """Add leaflet-image export script inside map HTML."""
    try:
        with open(html_path, "r", encoding="utf-8") as f:
            html = f.read()
        
        # Skip if already injected
        if "leaflet-image" in html and "EXPORT_MAP" in html:
            return

        injector = """
          <!-- Leaflet image export -->
          <script src="https://unpkg.com/leaflet-image/leaflet-image.js"></script>
          <script>
          (function(){
            function findLeafletMap(){
              for (const k in window){
                try{ const v = window[k]; if (v && v instanceof L.Map) return v; }catch(e){}
              }
              return null;
            }
            window.addEventListener('message', function(e){
              const msg = e.data || {};
              if (msg.type === 'EXPORT_MAP'){
                const map = findLeafletMap();
                if (!map || typeof window.leafletImage !== 'function'){
                  parent.postMessage({type:'EXPORT_MAP_RESULT', error:'no-map'}, '*'); return;
                }
                try{
                  window.leafletImage(map, function(err, canvas){
                    if (err){ parent.postMessage({type:'EXPORT_MAP_RESULT', error:String(err)}, '*'); return; }
                    var url = canvas.toDataURL('image/png');
                    parent.postMessage({type:'EXPORT_MAP_RESULT', dataURL:url}, '*');
                  });
                }catch(err){
                  parent.postMessage({type:'EXPORT_MAP_RESULT', error:String(err)}, '*');
                }
              }
            });
          })();
          </script>
        """
        
        # Insert script before </body> tag
        html = html.replace("</body>", injector + "\n</body>")
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html)
    
    except Exception:
        pass


# Helper to save a Folium map to file and inject export script
def _save_map(map, map_path):
    """Save Folium map and add PNG export support."""
    Path(os.path.dirname(map_path) or ".").mkdir(parents=True, exist_ok=True)
    map.save(map_path)
    _inject_exporter(map_path)

# Helper to delete map file on app shutdown
def _cleanup_map_file(map_path="static/map.html"):
    """Remove old map file if it exists."""
    try:
        if os.path.exists(map_path):
            os.remove(map_path)
    except Exception:
        pass


# Create an empty map centered on Uppsala
def build_empty_map(map_path):
    """Render an empty map centered on Uppsala."""
    map = folium.Map(location=[59.8586, 17.6389], zoom_start=12, tiles="OpenStreetMap")
    _save_map(map, map_path)

# Draw one route from a list of (lat, lon) points
def build_single_route_map(coords, name, map_path):
    """Render one route with line and fit bounds."""
    if not coords:
        return build_empty_map(map_path)
    
    # Start view at first coordinate
    map = folium.Map(location=[coords[0][0], coords[0][1]], zoom_start=13, tiles="OpenStreetMap")
    
    # Draw route
    folium.PolyLine(coords, weight=5, opacity=0.95, color="#FC5200", tooltip=name or "Route").add_to(map)
    
    # Adjust view to include all coordinates
    map.fit_bounds([[min(lat for lat, _ in coords), min(lon for _, lon in coords)],
                  [max(lat for lat, _ in coords), max(lon for _, lon in coords)]])
    
    _save_map(map, map_path)

# Draw a route from an encoded Strava polyline string
def build_polyline_route_map(polyline, name, map_path):
    """Render a route directly from an encoded polyline string."""
    pts = _decode_polyline(polyline) if polyline else []
    build_single_route_map(pts, name, map_path)