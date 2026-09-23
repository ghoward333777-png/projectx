-- Bridge sites declared in the config may promote host administrators to server administrators.
ALTER TABLE bridge_sites ADD COLUMN admin_sso INTEGER NOT NULL DEFAULT 0;
