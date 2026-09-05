-- Run only against the dedicated disposable MapleBench database after Cosmic migrations.
-- Synthetic offline characters; runtime IDs are resolved by name, never assumed.
-- INSERT-only setup is idempotent. The batch runner resets each trial's stats from its scenario.
INSERT INTO characters
  (accountid, world, name, level, exp, str, dex, luk, `int`, hp, mp, maxhp, maxmp,
   job, skincolor, gender, hair, face, map, meso)
SELECT 1, 0, 'Agent01', 15, 0, 70, 15, 4, 4, 500, 100, 500, 100,
       100, 0, 0, 30030, 20000, 100000000, 1000
WHERE NOT EXISTS (SELECT 1 FROM characters WHERE name = 'Agent01');

INSERT INTO characters
  (accountid, world, name, level, exp, str, dex, luk, `int`, hp, mp, maxhp, maxmp,
   job, skincolor, gender, hair, face, map, meso)
SELECT 1, 0, 'Agent90', 100, 0, 350, 120, 4, 4, 4000, 1000, 4000, 1000,
       111, 0, 0, 30030, 20000, 100000000, 1000
WHERE NOT EXISTS (SELECT 1 FROM characters WHERE name = 'Agent90');

INSERT INTO characters
  (accountid, world, name, level, exp, str, dex, luk, `int`, hp, mp, maxhp, maxmp,
   job, skincolor, gender, hair, face, map, meso)
SELECT 1, 0, 'AgentHero', 130, 0, 500, 120, 4, 4, 8000, 2000, 8000, 2000,
       112, 0, 0, 30030, 20000, 261020300, 1000
WHERE NOT EXISTS (SELECT 1 FROM characters WHERE name = 'AgentHero');

SELECT id, name, level, job, map FROM characters WHERE name IN ('Agent01', 'Agent90', 'AgentHero');
