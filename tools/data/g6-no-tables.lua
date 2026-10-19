-- A paper's tables, left out of what tools/g6_baseline.py measures: a manuscript's tables
-- are emitted and bound, and G6 does not count them, while a paper's bold marks values in
-- its tables (round 1 of #339).
function Table(_)
  return {}
end
