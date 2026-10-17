mersel@mersel:~/Documents/Projects/FreelanceDZ$ python -m venv .venv && source .venv/bin/activate
(.venv) mersel@mersel:~/Documents/Projects/FreelanceDZ$ pip install --default-timeout=120 -r requirements-ui.txt

Collecting streamlit>=1.41.0 (from -r requirements-ui.txt (line 13))
  Using cached streamlit-1.66.0-py3-none-any.whl.metadata (10 kB)
Collecting streamlit-folium>=0.23.0 (from -r requirements-ui.txt (line 14))
  Using cached streamlit_folium-0.27.4-py3-none-any.whl.metadata (2.1 kB)
Collecting folium>=0.19.0 (from -r requirements-ui.txt (line 15))
  Using cached folium-0.20.0-py2.py3-none-any.whl.metadata (4.2 kB)
Collecting pandas>=2.2.0 (from -r requirements-ui.txt (line 16))
  Using cached pandas-3.0.6-cp312-cp312-manylinux_2_24_x86_64.manylinux_2_28_x86_64.whl.metadata (79 kB)
Requirement already satisfied: httpx>=0.28.0 in ./.venv/lib/python3.12/site-packages (from -r requirements-ui.txt (line 17)) (0.28.1)
Collecting altair!=5.4.0,!=5.4.1,<7,>=5.0.0 (from streamlit>=1.41.0->-r requirements-ui.txt (line 13))
  Using cached altair-6.3.0-py3-none-any.whl.metadata (11 kB)
Requirement already satisfied: click<9,>=7.0 in ./.venv/lib/python3.12/site-packages (from streamlit>=1.41.0->-r requirements-ui.txt (line 13)) (8.1.8)
Collecting numpy<3,>=1.25.0 (from streamlit>=1.41.0->-r requirements-ui.txt (line 13))
  Using cached numpy-2.5.4-cp312-cp312-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl.metadata (6.6 kB)
Requirement already satisfied: packaging>=20 in ./.venv/lib/python3.12/site-packages (from streamlit>=1.41.0->-r requirements-ui.txt (line 13)) (26.3)
Collecting pillow<13,>=9.2.0 (from streamlit>=1.41.0->-r requirements-ui.txt (line 13))
  Using cached pillow-12.3.0-cp312-cp312-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl.metadata (9.1 kB)
Collecting pydeck<1,>=0.8.0b4 (from streamlit>=1.41.0->-r requirements-ui.txt (line 13))
  Using cached pydeck-0.9.3-py2.py3-none-any.whl.metadata (4.2 kB)
Collecting protobuf<8,>=5.26.1 (from streamlit>=1.41.0->-r requirements-ui.txt (line 13))
  Using cached protobuf-7.36.2-cp310-abi3-manylinux2014_x86_64.whl.metadata (595 bytes)
Collecting pyarrow!=25.0.0,<27,>=10.0.1 (from streamlit>=1.41.0->-r requirements-ui.txt (line 13))
  Using cached pyarrow-26.0.0-cp312-cp312-manylinux_2_28_x86_64.whl.metadata (3.0 kB)
Requirement already satisfied: requests<3,>=2.27 in ./.venv/lib/python3.12/site-packages (from streamlit>=1.41.0->-r requirements-ui.txt (line 13)) (2.34.2)
Requirement already satisfied: typing-extensions<5,>=4.10.0 in ./.venv/lib/python3.12/site-packages (from streamlit>=1.41.0->-r requirements-ui.txt (line 13)) (4.15.0)
Collecting starlette<2,>=0.46.0 (from streamlit>=1.41.0->-r requirements-ui.txt (line 13))
  Downloading starlette-1.8.0-py3-none-any.whl.metadata (6.6 kB)
Requirement already satisfied: uvicorn<1,>=0.30.0 in ./.venv/lib/python3.12/site-packages (from streamlit>=1.41.0->-r requirements-ui.txt (line 13)) (0.34.0)
Requirement already satisfied: anyio<5,>=4.0.0 in ./.venv/lib/python3.12/site-packages (from streamlit>=1.41.0->-r requirements-ui.txt (line 13)) (4.14.1)
Requirement already satisfied: python-multipart<1,>=0.0.10 in ./.venv/lib/python3.12/site-packages (from streamlit>=1.41.0->-r requirements-ui.txt (line 13)) (0.0.20)
Requirement already satisfied: websockets<18,>=12.0.0 in ./.venv/lib/python3.12/site-packages (from streamlit>=1.41.0->-r requirements-ui.txt (line 13)) (16.0)
Collecting itsdangerous<3,>=2.1.2 (from streamlit>=1.41.0->-r requirements-ui.txt (line 13))
  Using cached itsdangerous-2.2.0-py3-none-any.whl.metadata (1.9 kB)
Collecting watchdog<7,>=2.1.5 (from streamlit>=1.41.0->-r requirements-ui.txt (line 13))
  Using cached watchdog-6.0.0-py3-none-manylinux2014_x86_64.whl.metadata (44 kB)
Requirement already satisfied: jinja2 in ./.venv/lib/python3.12/site-packages (from streamlit-folium>=0.23.0->-r requirements-ui.txt (line 14)) (3.1.5)
Collecting branca (from streamlit-folium>=0.23.0->-r requirements-ui.txt (line 14))
  Using cached branca-0.8.2-py3-none-any.whl.metadata (1.7 kB)
Collecting xyzservices (from folium>=0.19.0->-r requirements-ui.txt (line 15))
  Using cached xyzservices-2026.9.1-py3-none-any.whl.metadata (4.1 kB)
Collecting python-dateutil>=2.8.2 (from pandas>=2.2.0->-r requirements-ui.txt (line 16))
  Using cached python_dateutil-2.9.0.post0-py2.py3-none-any.whl.metadata (8.4 kB)
Requirement already satisfied: certifi in ./.venv/lib/python3.12/site-packages (from httpx>=0.28.0->-r requirements-ui.txt (line 17)) (2026.6.17)
Requirement already satisfied: httpcore==1.* in ./.venv/lib/python3.12/site-packages (from httpx>=0.28.0->-r requirements-ui.txt (line 17)) (1.0.9)
Requirement already satisfied: idna in ./.venv/lib/python3.12/site-packages (from httpx>=0.28.0->-r requirements-ui.txt (line 17)) (3.18)
Requirement already satisfied: h11>=0.16 in ./.venv/lib/python3.12/site-packages (from httpcore==1.*->httpx>=0.28.0->-r requirements-ui.txt (line 17)) (0.16.0)
Collecting jsonschema>=3.0 (from altair!=5.4.0,!=5.4.1,<7,>=5.0.0->streamlit>=1.41.0->-r requirements-ui.txt (line 13))
  Using cached jsonschema-4.26.0-py3-none-any.whl.metadata (7.6 kB)
Collecting narwhals>=2.4.0 (from altair!=5.4.0,!=5.4.1,<7,>=5.0.0->streamlit>=1.41.0->-r requirements-ui.txt (line 13))
  Using cached narwhals-2.27.1-py3-none-any.whl.metadata (15 kB)
Requirement already satisfied: MarkupSafe>=2.0 in ./.venv/lib/python3.12/site-packages (from jinja2->streamlit-folium>=0.23.0->-r requirements-ui.txt (line 14)) (3.0.3)
Collecting six>=1.5 (from python-dateutil>=2.8.2->pandas>=2.2.0->-r requirements-ui.txt (line 16))
  Using cached six-1.17.0-py2.py3-none-any.whl.metadata (1.7 kB)
Requirement already satisfied: charset_normalizer<4,>=2 in ./.venv/lib/python3.12/site-packages (from requests<3,>=2.27->streamlit>=1.41.0->-r requirements-ui.txt (line 13)) (3.4.7)
Requirement already satisfied: urllib3<3,>=1.26 in ./.venv/lib/python3.12/site-packages (from requests<3,>=2.27->streamlit>=1.41.0->-r requirements-ui.txt (line 13)) (2.7.0)
Collecting attrs>=22.2.0 (from jsonschema>=3.0->altair!=5.4.0,!=5.4.1,<7,>=5.0.0->streamlit>=1.41.0->-r requirements-ui.txt (line 13))
  Using cached attrs-26.1.0-py3-none-any.whl.metadata (8.8 kB)
Collecting jsonschema-specifications>=2023.03.6 (from jsonschema>=3.0->altair!=5.4.0,!=5.4.1,<7,>=5.0.0->streamlit>=1.41.0->-r requirements-ui.txt (line 13))
  Using cached jsonschema_specifications-2025.9.1-py3-none-any.whl.metadata (2.9 kB)
Collecting referencing>=0.28.4 (from jsonschema>=3.0->altair!=5.4.0,!=5.4.1,<7,>=5.0.0->streamlit>=1.41.0->-r requirements-ui.txt (line 13))
  Using cached referencing-0.37.0-py3-none-any.whl.metadata (2.8 kB)
Collecting rpds-py>=0.25.0 (from jsonschema>=3.0->altair!=5.4.0,!=5.4.1,<7,>=5.0.0->streamlit>=1.41.0->-r requirements-ui.txt (line 13))
  Using cached rpds_py-2026.9.1-cp312-cp312-manylinux_2_17_x86_64.manylinux2014_x86_64.whl.metadata (4.1 kB)
Downloading streamlit-1.66.0-py3-none-any.whl (10.4 MB)
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 10.4/10.4 MB 127.4 kB/s eta 0:00:00
Downloading streamlit_folium-0.27.4-py3-none-any.whl (536 kB)
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 536.9/536.9 kB 787.0 kB/s eta 0:00:00
Downloading folium-0.20.0-py2.py3-none-any.whl (113 kB)
Using cached pandas-3.0.6-cp312-cp312-manylinux_2_24_x86_64.manylinux_2_28_x86_64.whl (10.8 MB)
Downloading altair-6.3.0-py3-none-any.whl (797 kB)
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 797.2/797.2 kB 605.4 kB/s eta 0:00:00
Downloading branca-0.8.2-py3-none-any.whl (26 kB)
Downloading itsdangerous-2.2.0-py3-none-any.whl (16 kB)
Downloading numpy-2.5.4-cp312-cp312-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl (16.7 MB)
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 16.7/16.7 MB 1.2 MB/s eta 0:00:00
Using cached pillow-12.3.0-cp312-cp312-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl (6.9 MB)
Downloading protobuf-7.36.2-cp310-abi3-manylinux2014_x86_64.whl (343 kB)
Downloading pyarrow-26.0.0-cp312-cp312-manylinux_2_28_x86_64.whl (53.9 MB)
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 53.9/53.9 MB 2.1 MB/s eta 0:00:00
Downloading pydeck-0.9.3-py2.py3-none-any.whl (11.4 MB)
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 11.4/11.4 MB 2.0 MB/s eta 0:00:00
Downloading python_dateutil-2.9.0.post0-py2.py3-none-any.whl (229 kB)
Downloading starlette-1.8.0-py3-none-any.whl (79 kB)
Downloading watchdog-6.0.0-py3-none-manylinux2014_x86_64.whl (79 kB)
Downloading xyzservices-2026.9.1-py3-none-any.whl (98 kB)
Downloading jsonschema-4.26.0-py3-none-any.whl (90 kB)
Downloading narwhals-2.27.1-py3-none-any.whl (483 kB)
Downloading six-1.17.0-py2.py3-none-any.whl (11 kB)
Downloading attrs-26.1.0-py3-none-any.whl (67 kB)
Downloading jsonschema_specifications-2025.9.1-py3-none-any.whl (18 kB)
Downloading referencing-0.37.0-py3-none-any.whl (26 kB)
Downloading rpds_py-2026.9.1-cp312-cp312-manylinux_2_17_x86_64.manylinux2014_x86_64.whl (371 kB)
Installing collected packages: xyzservices, watchdog, six, rpds-py, pyarrow, protobuf, pillow, numpy, narwhals, itsdangerous, attrs, starlette, referencing, python-dateutil, pydeck, branca, pandas, jsonschema-specifications, folium, jsonschema, altair, streamlit, streamlit-folium
  Attempting uninstall: starlette
    Found existing installation: starlette 0.41.3
    Uninstalling starlette-0.41.3:
      Successfully uninstalled starlette-0.41.3
ERROR: pip's dependency resolver does not currently take into account all the packages that are installed. This behaviour is the source of the following dependency conflicts.
fastapi 0.115.6 requires starlette<0.42.0,>=0.40.0, but you have starlette 1.8.0 which is incompatible.
Successfully installed altair-6.3.0 attrs-26.1.0 branca-0.8.2 folium-0.20.0 itsdangerous-2.2.0 jsonschema-4.26.0 jsonschema-specifications-2025.9.1 narwhals-2.27.1 numpy-2.5.4 pandas-3.0.6 pillow-12.3.0 protobuf-7.36.2 pyarrow-26.0.0 pydeck-0.9.3 python-dateutil-2.9.0.post0 referencing-0.37.0 rpds-py-2026.9.1 six-1.17.0 starlette-1.8.0 streamlit-1.66.0 streamlit-folium-0.27.4 watchdog-6.0.0 xyzservices-2026.9.1
(.venv) mersel@mersel:~/Documents/Projects/FreelanceDZ$ 
(.venv) mersel@mersel:~/Documents/Projects/FreelanceDZ$ python cli.py serve      # engine  → http://localhost:8080 (docs at /docs)
Serving on http://0.0.0.0:8080
/home/mersel/Documents/Projects/FreelanceDZ/.venv/lib/python3.12/site-packages/fastapi/applications.py:18: StarletteDeprecationWarning: 'HTTP_422_UNPROCESSABLE_ENTITY' is deprecated. Use 'HTTP_422_UNPROCESSABLE_CONTENT' instead.
  from fastapi.exception_handlers import (
/home/mersel/Documents/Projects/FreelanceDZ/.venv/lib/python3.12/site-packages/fastapi/applications.py:30: StarletteDeprecationWarning: 'HTTP_422_UNPROCESSABLE_ENTITY' is deprecated. Use 'HTTP_422_UNPROCESSABLE_CONTENT' instead.
  from fastapi.openapi.utils import get_openapi
Traceback (most recent call last):
  File "/home/mersel/Documents/Projects/FreelanceDZ/cli.py", line 211, in <module>
    cli()
  File "/home/mersel/Documents/Projects/FreelanceDZ/.venv/lib/python3.12/site-packages/click/core.py", line 1161, in __call__
    return self.main(*args, **kwargs)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/mersel/Documents/Projects/FreelanceDZ/.venv/lib/python3.12/site-packages/click/core.py", line 1082, in main
    rv = self.invoke(ctx)
         ^^^^^^^^^^^^^^^^
  File "/home/mersel/Documents/Projects/FreelanceDZ/.venv/lib/python3.12/site-packages/click/core.py", line 1697, in invoke
    return _process_result(sub_ctx.command.invoke(sub_ctx))
                           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/mersel/Documents/Projects/FreelanceDZ/.venv/lib/python3.12/site-packages/click/core.py", line 1443, in invoke
    return ctx.invoke(self.callback, **ctx.params)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/mersel/Documents/Projects/FreelanceDZ/.venv/lib/python3.12/site-packages/click/core.py", line 788, in invoke
    return __callback(*args, **kwargs)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/mersel/Documents/Projects/FreelanceDZ/cli.py", line 133, in serve
    uvicorn.run("api.server:app", host=bind_host, port=bind_port, reload=False)
  File "/home/mersel/Documents/Projects/FreelanceDZ/.venv/lib/python3.12/site-packages/uvicorn/main.py", line 579, in run
    server.run()
  File "/home/mersel/Documents/Projects/FreelanceDZ/.venv/lib/python3.12/site-packages/uvicorn/server.py", line 66, in run
    return asyncio.run(self.serve(sockets=sockets))
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/usr/lib/python3.12/asyncio/runners.py", line 194, in run
    return runner.run(main)
           ^^^^^^^^^^^^^^^^
  File "/usr/lib/python3.12/asyncio/runners.py", line 118, in run
    return self._loop.run_until_complete(task)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "uvloop/loop.pyx", line 1518, in uvloop.loop.Loop.run_until_complete
  File "/home/mersel/Documents/Projects/FreelanceDZ/.venv/lib/python3.12/site-packages/uvicorn/server.py", line 70, in serve
    await self._serve(sockets)
  File "/home/mersel/Documents/Projects/FreelanceDZ/.venv/lib/python3.12/site-packages/uvicorn/server.py", line 77, in _serve
    config.load()
  File "/home/mersel/Documents/Projects/FreelanceDZ/.venv/lib/python3.12/site-packages/uvicorn/config.py", line 435, in load
    self.loaded_app = import_from_string(self.app)
                      ^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/mersel/Documents/Projects/FreelanceDZ/.venv/lib/python3.12/site-packages/uvicorn/importer.py", line 19, in import_from_string
    module = importlib.import_module(module_str)
             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/usr/lib/python3.12/importlib/__init__.py", line 90, in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "<frozen importlib._bootstrap>", line 1387, in _gcd_import
  File "<frozen importlib._bootstrap>", line 1360, in _find_and_load
  File "<frozen importlib._bootstrap>", line 1310, in _find_and_load_unlocked
  File "<frozen importlib._bootstrap>", line 488, in _call_with_frames_removed
  File "<frozen importlib._bootstrap>", line 1387, in _gcd_import
  File "<frozen importlib._bootstrap>", line 1360, in _find_and_load
  File "<frozen importlib._bootstrap>", line 1331, in _find_and_load_unlocked
  File "<frozen importlib._bootstrap>", line 935, in _load_unlocked
  File "<frozen importlib._bootstrap_external>", line 995, in exec_module
  File "<frozen importlib._bootstrap>", line 488, in _call_with_frames_removed
  File "/home/mersel/Documents/Projects/FreelanceDZ/api/__init__.py", line 3, in <module>
    from api.server import app, create_app
  File "/home/mersel/Documents/Projects/FreelanceDZ/api/server.py", line 16, in <module>
    from api.routes import checkpoints as checkpoints_routes
  File "/home/mersel/Documents/Projects/FreelanceDZ/api/routes/__init__.py", line 3, in <module>
    from api.routes import checkpoints, geo, leads, misc
  File "/home/mersel/Documents/Projects/FreelanceDZ/api/routes/checkpoints.py", line 22, in <module>
    checkpoints_router = APIRouter(prefix="/api/v2/checkpoints", tags=["checkpoints"])
                         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/mersel/Documents/Projects/FreelanceDZ/.venv/lib/python3.12/site-packages/fastapi/routing.py", line 837, in __init__
    super().__init__(
TypeError: Router.__init__() got an unexpected keyword argument 'on_startup'
(.venv) mersel@mersel:~/Documents/Projects/FreelanceDZ$ 