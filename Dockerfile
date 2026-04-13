FROM python:3.14-rc-slim AS check

RUN pip install ruff==0.14.0 mypy==1.19.0 --break-system-packages

RUN ln -s $(which ruff) /usr/local/bin/ruff_bin && \
    printf '#!/bin/bash\nruff "$@"' > /ruff && chmod +x /ruff && \
    printf '#!/bin/bash\nmypy "$@"' > /mypy && chmod +x /mypy

RUN apt-get update && apt-get install -y nodejs npm && rm -rf /var/lib/apt/lists/*

WORKDIR /src
ENTRYPOINT ["/bin/bash"]

# ==================== BUILD-TEST (TS tester) ====================
FROM node:24-slim AS build-test

WORKDIR /src/tester
COPY tester/package.json tester/package-lock.json ./
RUN npm ci
COPY tester/ ./
RUN npm run build

# ==================== RUNTIME (Python interpret) ====================
FROM python:3.14-rc-slim AS runtime

WORKDIR /app
COPY int/requirements.txt ./
RUN pip install -r requirements.txt --break-system-packages

COPY int/ ./

ENTRYPOINT ["python3", "/app/src/solint.py"]

# ==================== TEST ====================
FROM runtime AS test

RUN apt-get update && apt-get install -y nodejs diffutils && rm -rf /var/lib/apt/lists/*

COPY --from=build-test /src/tester/dist /app/tester/dist
COPY --from=build-test /src/tester/package.json /app/tester/

ENV INTERPRETER=python3
ENV INTERPRETER_SCRIPT=/app/src/solint.py
ENV SOL2XML=sol2xml

ENTRYPOINT ["node", "/app/tester/dist/index.js"]