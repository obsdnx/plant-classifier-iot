import glob, json, re, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import serial

THRESHOLD_CM = 5
state = {"distance": None, "connected": False}

PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>Ultrasonic Dashboard</title>
<style>
 body{font-family:system-ui,sans-serif;background:#111;color:#eee;display:flex;flex-direction:column;
      align-items:center;justify-content:center;height:100vh;margin:0}
 #dist{font-size:96px;font-weight:700}
 #status{font-size:48px;margin-top:24px;padding:16px 40px;border-radius:16px;background:#333}
 #status.on{background:#2e7d32}
 #conn{position:fixed;top:12px;right:16px;font-size:14px;color:#888}
</style></head><body>
<div id="conn">connecting...</div>
<div id="dist">-- cm</div>
<div id="status">Waiting...</div>
<script>
async function tick(){
  try{
    const d = await (await fetch('/distance')).json();
    document.getElementById('conn').textContent = d.connected ? 'sensor connected' : 'sensor not connected';
    const s = document.getElementById('status');
    if(d.distance === null){ document.getElementById('dist').textContent='-- cm'; s.textContent='No reading'; s.className=''; }
    else{
      document.getElementById('dist').textContent = d.distance.toFixed(1)+' cm';
      if(d.distance < %d){ s.textContent='Hat activated'; s.className='on'; }
      else{ s.textContent='Hat not activated'; s.className=''; }
    }
  }catch(e){ document.getElementById('conn').textContent='dashboard offline'; }
}
setInterval(tick, 200); tick();
</script></body></html>""" % THRESHOLD_CM


def read_serial():
    while True:
        ports = glob.glob("/dev/cu.usbmodem*") + glob.glob("/dev/cu.usbserial-*")
        if not ports:
            state["connected"] = False
            time.sleep(1)
            continue
        try:
            with serial.Serial(ports[0], 115200, timeout=2) as ser:
                state["connected"] = True
                print("Reading sensor on", ports[0])
                while True:
                    line = ser.readline().decode(errors="ignore")
                    m = re.search(r"Distance:\s*([\d.]+)", line)
                    if m:
                        state["distance"] = float(m.group(1))
                    elif "No echo" in line:
                        state["distance"] = None
        except serial.SerialException as e:
            print("Serial error:", e)
            state["connected"] = False
            time.sleep(1)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/distance":
            body, ctype = json.dumps(state).encode(), "application/json"
        else:
            body, ctype = PAGE.encode(), "text/html"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    threading.Thread(target=read_serial, daemon=True).start()
    print("Dashboard: http://localhost:8001")
    ThreadingHTTPServer(("localhost", 8001), Handler).serve_forever()
