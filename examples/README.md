# performance-mapper examples

Each example lives in its own directory with its data, script, figures, and README.

| Example | What it shows |
|---------|---------------|
| [chiller](chiller/README.md) | Translates irregular inch-pound chiller operating data, with percent load, into a regular SI map with compressor sequence numbers. |

The examples' plotting dependencies (matplotlib and plotly) are in the `examples` dependency group, so it
is not installed with the core package. Run an example from the repository root:

```
uv run --group examples python examples/chiller/translate_to_regular_map.py
```
