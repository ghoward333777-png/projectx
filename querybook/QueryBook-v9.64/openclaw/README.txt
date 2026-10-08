CONNECTING OPENCLAW TO QUERYBOOK
================================

QueryBook gives OpenClaw cited facts, file ingestion (Open Claw), and provenance checks through
an MCP server. Every OpenClaw call passes through QueryBook's Agent Gateway and security shield.

1. Print the exact settings for this computer. Open a Command Prompt in the QueryBook folder:

       py qb_mcp.py --openclaw-config

   It shows an "mcp_server" block containing a private caller token. Keep that token private.

2. Add the "querybook" entry to the mcp.servers section of your OpenClaw config file
   (openclaw.json), then check the connection:

       openclaw mcp probe querybook

3. Install the QueryBook skill, which teaches OpenClaw when and how to use the tools:

       openclaw skills install <QueryBook folder>\openclaw\querybook --global

4. Put files you want OpenClaw to ingest in your inbox folder (shown by step 1, normally
   C:\Users\<you>\QueryBook-Inbox). For safety, OpenClaw cannot make QueryBook read files
   anywhere else on the computer.

WHAT OPENCLAW MAY DO
--------------------
Ask questions, verify claims, preview and ingest inbox files, verify the provenance ledger, and
check NFT certificates. It may not mint or transfer NFTs, change policies, or read the security
log's raw entries. To change what it may do, edit shield_policy.json (agent "qb.openclaw") and
restart QueryBook. Permissions never expand through the API.

IF OPENCLAW GETS ISOLATED
-------------------------
If OpenClaw, or something controlling it, triggers a trap, QueryBook isolates that session. All
further answers to it are synthetic, and everything it does is recorded. Review it with:

    py qb_shield.py status

Release it only if you are sure it was not an attack:

    py qb_shield.py release openclaw
