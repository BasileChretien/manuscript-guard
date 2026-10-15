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
and handed over in a JSON file named by the `mg-narrative` metadata: the source text of each
narrative citation, and the name printed before it.
]]

local names = {}

local function Meta(meta)
  local file = meta['mg-narrative']
  if file == nil then return nil end
  meta['mg-narrative'] = nil
  local handle = io.open(pandoc.utils.stringify(file), 'r')
  if handle ~= nil then
    names = pandoc.json.decode(handle:read('a'))
    handle:close()
  end
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
