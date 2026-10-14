# syntax=docker/dockerfile:1
#
# GIF Editor in a Linux container. Three uses, one image (see README "Docker"):
#   GUI over VNC (default)  docker run --rm -p 127.0.0.1:5900:5900 -v "$PWD:/work" gif-editor
#   GUI on an X11 display   ... -e QT_QPA_PLATFORM=xcb -e DISPLAY -v /tmp/.X11-unix:/tmp/.X11-unix
#   headless edit           docker run --rm -v "$PWD:/work" gif-editor --edit-spec in.gif "...,out=out.gif"
# The test suite is a separate target:  docker build --target test -t gif-editor-test .
#
# The Windows .exe is NOT built here: Nuitka cannot cross-compile (build-exe.yml does that).

# Python 3.13.16 on Debian 13 (trixie). Pinned by digest (multi-arch index) like every
# other dependency of this project; update tag and digest together.
FROM python:3.13.16-slim-trixie@sha256:70729b46c69b4f1e97c4822c1af3df53a1476cf5ddc6c087c0c10bc3a5678c2f AS app

# Shared libraries the PySide6 wheel needs and the slim image lacks. The list comes from
# `ldd` on Qt's Core/Gui/Widgets/XcbQpa libraries and the xcb, vnc and offscreen platform
# plugins (docs/codebase/Dockerfile.md). Plus one font: without any font Qt draws boxes.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      libegl1 libgl1 libglib2.0-0t64 libdbus-1-3 libfontconfig1 libfreetype6 libatomic1 \
      libgssapi-krb5-2 \
      libx11-6 libx11-xcb1 libxcb1 libxcb-cursor0 libxcb-icccm4 libxcb-image0 \
      libxcb-keysyms1 libxcb-randr0 libxcb-render0 libxcb-render-util0 libxcb-shape0 \
      libxcb-shm0 libxcb-sync1 libxcb-xfixes0 libxcb-xkb1 libxkbcommon0 libxkbcommon-x11-0 \
      fonts-dejavu-core \
 && rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /opt/gif-editor
COPY requirements.txt ./
RUN pip install -r requirements.txt
COPY src/ src/

# Unprivileged user. /work is where you mount your GIFs (the file dialogs open there).
RUN useradd --create-home --uid 1000 app && install -d -o app -g app /work
USER app
WORKDIR /work

# QT_QPA_PLATFORM: Qt's built-in VNC server by default, so the GUI works on any host with
# just a VNC viewer (no X server). It has no password: publish the port on 127.0.0.1 only.
# XDG_RUNTIME_DIR: Qt wants one; it creates the folder itself.
ENV PYTHONPATH=/opt/gif-editor/src \
    QT_QPA_PLATFORM=vnc:size=1600x1000 \
    XDG_RUNTIME_DIR=/tmp/runtime-app
EXPOSE 5900
ENTRYPOINT ["python", "-m", "gif_editor"]


# ---------------------------------------------------------------- test suite
# docker build --target test -t gif-editor-test . && docker run --rm gif-editor-test
FROM app AS test
USER root
WORKDIR /opt/gif-editor
COPY requirements-dev.txt ./
COPY packaging/build-requirements.txt packaging/
# build-requirements: tests/core/test_check_build_flags.py runs Nuitka's option parser.
RUN pip install -r requirements-dev.txt -r packaging/build-requirements.txt
COPY pyproject.toml ./
COPY scripts/ scripts/
COPY tests/ tests/
USER app
# Same 3840x2160 virtual screen as scripts/test.sh (the default 800x600 loses mouse events).
ENV QT_QPA_PLATFORM=offscreen:configfile=/opt/gif-editor/scripts/offscreen-screen.json
ENTRYPOINT ["python", "-m", "pytest", "-q", "-p", "no:cacheprovider"]


# ---------------------------------------------------------------- the app (default)
# Last on purpose: a plain `docker build -t gif-editor .` builds the LAST stage. It inherits
# everything (user, workdir, env, port, entrypoint) from `app`.
FROM app AS runtime
