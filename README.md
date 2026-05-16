# Tourism Route Recommendation System

This project is a Windows-focused Web application for tourism route recommendation. It mines `simple cycle` route patterns from historical trajectory data and returns Top-K recommendations based on category preferences, season, start point, required POIs, time budget, hard filters, and soft ranking priorities.

## Overview

The current runtime entrypoints are:

- `start.bat`: the recommended Windows one-click launcher
- `main.py`: the Python Web launcher
- `web_api.py`: the FastAPI application

By default, the system starts a local Web service and opens:

```text
http://127.0.0.1:8000/
```

## Requirements

This repository currently provides Windows run instructions only.

Before running the project, make sure you have:

- Windows 10 or later
- Python 3.10 or later
- `pip`
- A desktop browser such as Edge, Chrome, or Firefox

Check whether Python is available:

```powershell
python --version
```

If `python` is not recognized, reinstall Python and enable:

```text
Add Python to PATH
```

## Dependencies

All Python dependencies are listed in `requirements.txt`.

Main runtime dependencies:

- `fastapi`
- `uvicorn`
- `pydantic`
- `python-multipart`
- `pandas`
- `numpy`
- `networkx`

## Run Option 1: Double-click `start.bat`

This is the recommended way for normal use on Windows.

From the project root, double-click:

```text
start.bat
```

What `start.bat` does:

1. Creates `.venv` if it does not exist
2. Activates the virtual environment
3. Upgrades `pip`
4. Installs dependencies from `requirements.txt`
5. Runs `main.py`
6. Starts the Web service
7. Opens the browser automatically when the service is ready

If the browser does not open automatically, open this URL manually:

```text
http://127.0.0.1:8000/
```

## Run Option 2: Run `start.bat` from Terminal

You can also start the project from PowerShell:

```powershell
cd tourism_route_demo
.\start.bat
```

This does the same setup and launch flow as double-clicking the file.

## Run Option 3: Manual Setup with `.venv`

If you prefer to manage the environment yourself, run the following commands from the project root:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

This is the most reliable manual method because it uses the project virtual environment explicitly.

## Run Option 4: Run `python main.py` Directly

The normal Python entrypoint is:

```powershell
python main.py
```

However, this works only if the current Python interpreter already has the required packages installed.

If you want to run `main.py` directly after using `start.bat`, use the `.venv` interpreter:

```powershell
.\.venv\Scripts\python.exe main.py
```

You can also activate the environment first:

```powershell
.\.venv\Scripts\activate.bat
python main.py
```

## IDE Note: Why `main.py` May Fail After `start.bat`

Running `start.bat` once does not permanently switch your IDE or terminal to `.venv`.

If you run `main.py` from PyCharm or VS Code, make sure the interpreter is set to:

```text
tourism_route_demo\.venv\Scripts\python.exe
```

If your IDE uses a different interpreter, you may still get errors such as:

```text
ModuleNotFoundError: No module named 'uvicorn'
```

## What `main.py` Does

`main.py` is still the real Python launcher. It:

1. Starts `uvicorn`
2. Serves the FastAPI app from `web_api:app`
3. Waits until the local service is reachable
4. Opens the default browser automatically

`start.bat` is only a Windows wrapper around that launcher.

## Data Files

The system uses these default runtime files:

```text
data/poi.csv
data/trajectory.csv
```

If these files do not exist, the Web app can still start, but recommendation features will require data import from the browser UI.
Note that the database currently being used is only a simulated database with a very small amount of data. It is only used to test the system. Without setting personalized conditions, it can only discover about 10 routes at most. In addition, it may not be able to discover any routes under some personalized conditions. It is recommended to set the time budget to more than 5 hours.

Required fields for `poi.csv`:

- `poi_id`
- `poi_name`
- `category`
- `latitude`
- `longitude`

Required fields for `trajectory.csv`:

- `user_id`
- `trajectory_id`
- `visit_order`
- `poi_id`
- `timestamp`

## Troubleshooting

### `No module named 'uvicorn'`

This usually means the Python interpreter that is running `main.py` is not the same one that installed the dependencies.

Try:

```powershell
python -m pip install -r requirements.txt
python main.py
```

Or use the safer project-local interpreter:

```powershell
.\.venv\Scripts\python.exe main.py
```

### Dependencies were installed, but `main.py` still fails

Check which Python is currently active:

```powershell
python -c "import sys; print(sys.executable)"
```

Check whether `uvicorn` is installed in that same environment:

```powershell
python -m pip show uvicorn
```

### Port `8000` is already in use

Check the process using the port:

```powershell
netstat -ano | findstr :8000
```

### Browser opens on the same machine only

The current default host is `127.0.0.1`, so the app is intended for local access on the same computer:

```text
http://127.0.0.1:8000/
```

If you need access from another machine, you would need to change the host binding in `main.py`.

## Stop the Server

If you started the app from a terminal window, press:

```text
Ctrl+C
```

If you started it by double-clicking `start.bat`, close that terminal window to stop the server.
