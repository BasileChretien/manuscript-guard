-- A paper's tables, left out of what tools/g6_baseline.py measures: a manuscript's tables
-- are emitted and bound, and G6 does not count them, while a paper's bold marks values in
-- its tables (round 1 of #339).
function Table(_)
  return {}
end

-- JATS keeps a table's caption and its foot outside the table, in the table-wrap pandoc
-- reads as a Div, and both carry bold of their own (round 2 of #339).
function Div(div)
  if div.classes:includes("table-wrap") then
    return {}
  end
end
