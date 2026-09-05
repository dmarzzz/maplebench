-- Run only against the dedicated, disposable MapleBench database after Cosmic migrations.
-- These are synthetic game characters, not real accounts or personal data.
INSERT INTO characters
  (accountid, world, name, level, exp, str, dex, luk, `int`, hp, mp, maxhp, maxmp,
   job, skincolor, gender, hair, face, map, meso)
SELECT 1, 0, 'Agent01', 15, 0, 70, 15, 4, 4, 500, 100, 500, 100,
       100, 0, 0, 30030, 20000, 100000000, 1000
WHERE NOT EXISTS (SELECT 1 FROM characters WHERE name = 'Agent01');
SELECT id, name, level, map FROM characters WHERE name = 'Agent01';
