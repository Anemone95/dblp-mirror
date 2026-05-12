# DBLP search Alfred workflow #

## Usage
Configure `settings.py` in the repository root:

- `DBLP_SERVER`: base URL of your private DBLP search server, for example `https://dblp.example.com`
- `DBLP_TOKEN`: bearer token configured on the server

You can also override these values in Alfred workflow configuration.

Open up Alfred, type `dblp` and then the query terms separated by `SPACE`.

Hit `↩` to copy bibtex in clipboard

Keep filtering your results by adding new terms.


## Build

Run `make workflow` or `make install` from the repository root.
