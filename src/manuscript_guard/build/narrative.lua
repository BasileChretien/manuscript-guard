--[[
In the build `import` compares a live document with, the author's name before a narrative
citation (`@key`), as the live build printed it.

Better BibTeX's zotero.lua writes a narrative citation as the author's name, in a run of
plain text, then a field that leaves the author out. The comparison prints each citation as
the source writes it, `@key`, and a returned document reads "Smith @key": the name was a
difference no one made, and it read as prose a co-author had typed. Put inside the citation,
where the live build's name stood, it reads the same on both sides and is part of the
citation, as a style's would be.

The names are the live build's own, read from the document it made and recorded beside it,
and handed over in the `mg-narrative` metadata as JSON written in hexadecimal: the source text
of each narrative citation, and the name printed before it. Not in a file: Lua opens a file
by a path in the bytes Windows gives it, and a temporary folder under a name with an accent
was not opened, the names were none, and the name was read as prose again. Names that cannot
be read stop the build, which `import` then reports, rather than compare without them.
]]

local names = {}

local function Meta(meta)
  local given = meta['mg-narrative']
  if given == nil then return nil end
  meta['mg-narrative'] = nil
  local hex = pandoc.utils.stringify(given)
  local ok, decoded = pcall(function()
    -- In parentheses: gsub also returns its count, which decode would take as an argument.
    return pandoc.json.decode((hex:gsub('..', function(pair)
      return string.char(tonumber(pair, 16))
    end)))
  end)
  if not ok or type(decoded) ~= 'table' then
    error('narrative.lua: the names of the narrative citations could not be read')
  end
  names = decoded
  return meta
end

local function Cite(cite)
  if cite.citations[1].mode ~= 'AuthorInText' then return nil end
  local name = names[pandoc.utils.stringify(cite.content)]
  if type(name) ~= 'string' then return nil end
  cite.content = pandoc.List({ pandoc.Str(name) }) .. cite.content
  return cite
end

return {
  { Meta = Meta },
  { Cite = Cite },
}
