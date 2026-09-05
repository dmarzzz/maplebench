-- Optional stronger fixture in the dedicated disposable experiment database.
-- Separate synthetic character; does not overwrite the baseline Agent01.
INSERT INTO characters
  (accountid, world, name, level, exp, str, dex, luk, `int`, hp, mp, maxhp, maxmp,
   job, skincolor, gender, hair, face, map, meso)
SELECT 1, 0, 'Agent90', 100, 0, 350, 120, 4, 4, 4000, 1000, 4000, 1000,
       111, 0, 0, 30030, 20000, 100000000, 1000
WHERE NOT EXISTS (SELECT 1 FROM characters WHERE name = 'Agent90');
SELECT id, name, level, map FROM characters WHERE name = 'Agent90';
