"""Product agents ("Riset Produk"): research and reports for the people who
decide what a project builds next, next to Awak, which builds it.

Four agents, one run each (a background job that ends in a Markdown report):

- competitor: searches the web for the product's competitors;
- features:   reads the code and the backlog (and a competitor run, if
              given) and proposes what to build, as suggestions Intake can
              turn into stories;
- report:     pulls the project's delivery data and writes it up; every
              number is computed here, the model only writes the prose;
- custom:     a free brief, with the web when the server has it.

The web is reached only through `kemudi-riset` (Hermes with its web tools
and nothing else: no files, no terminal, no project secrets). That agent
gets the brief and a short product summary, never the code or the backlog;
whatever it reads on the web is data to it, and its answer is data to us.
"""

KINDS = ("competitor", "features", "report", "custom")
NEEDS_WEB = {"competitor": True, "features": False, "report": False, "custom": True}
