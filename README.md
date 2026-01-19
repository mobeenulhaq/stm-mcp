# STM MCP Server

An MCP (Model Context Protocol) server for Montreal's STM transit system.

## Features

- Natural language transit queries
- Real-time bus/metro arrivals
- Trip planning
- Service alerts

## Installation

```bash
pip install -e ".[dev]"
```

## Usage

```bash
stm-mcp
```

## Development

```bash
# Run tests
pytest

# Lint
ruff check src tests

# Format
ruff format src tests
```

## License

MIT
