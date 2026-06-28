# SOL26 XML Interpreter

A Python interpreter for the **SOL26** language developed as part of the **IPP (Principles of Programming Languages)** course at **VUT FIT**.

The project contains:

- A **Python interpreter** capable of executing SOL26 programs represented as an XML Abstract Syntax Tree (AST).
- A **TypeScript** automated testing framework for validating interpreter functionality.
- A **Dockerized** development and testing environment.

## Features

- XML AST parsing and validation
- Execution of the SOL26 instruction set
- Runtime management of variables, frames, and control flow
- Specification-compliant runtime error handling
- Automated testing framework written in TypeScript
- Static analysis using Ruff and MyPy
- Multi-stage Docker builds for development, testing, and deployment

## Technologies

- Python 3.14
- TypeScript
- Docker
- Ruff
- MyPy
- Node.js

## Repository Structure

```text
.
├── python/              # Python interpreter
├── typescript/          # TypeScript testing framework
├── Dockerfile
└── README.md
```

This repository is organized according to the development layout.

To build and test the project using the submitted structure, move the contents of the `python/` and `typescript/` directories into the repository root (next to the `Dockerfile`) and remove the now-empty directories. The resulting structure matches the layout required by the course specification.

## Docker

The project provides a multi-stage Dockerfile:

| Stage | Purpose |
|------|---------|
| `check` | Development environment with Ruff, MyPy, Node.js, and npm |
| `build-test` | Builds the TypeScript testing framework |
| `runtime` | Lightweight interpreter image |
| `test` | Interpreter bundled with the compiled tester |

### Build the interpreter image

```bash
docker build --target runtime -t sol26 .
```

### Run the interpreter

```bash
docker run --rm -i sol26 < program.xml
```

### Build the testing image

```bash
docker build --target test -t sol26-test .
```

### Run the automated tests

```bash
docker run --rm sol26-test
```

## Local Development

Install Python dependencies:

```bash
pip install -r python/int/requirements.txt
```

Install tester dependencies:

```bash
cd typescript/tester
npm install
npm run build
```

Run the interpreter:

```bash
python3 python/int/src/solint.py
```

## Quality Assurance

The project includes:

- Ruff for linting
- MyPy for static type checking
- Automated integration tests written in TypeScript
- Dockerized execution environment for reproducible testing

## Evaluation

Final course project grade:

**17.5 / 20 points (87.5%)**
