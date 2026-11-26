--[[
A heading over the reference list of the Word document.

pandoc's citeproc puts the reference list where the manuscript writes `::: {#refs}` / `:::`, or
at the end, with no heading of its own unless `reference-section-title` is set, and that
setting is passed over where the manuscript has a `refs` div. A live build's bibliography
field goes in the same place (`zotero_word.lua`). So a manuscript that did not end with its
own "# References" built into a document whose references followed the last statement as if
they were part of it.

Run after citeproc on an offline build, and before `zotero_word.lua` on a live one, this
filter puts a first-level heading, unnumbered, before the reference list, titled as the
`mg-references-heading` metadata says: JSON written in hexadecimal, as `narrative.lua` takes
its names, so that the command line carries any title. It adds none where the author wrote
one: where the block before the list, comments aside, is a heading, which is also where
citeproc puts the list of a manuscript that ends with a heading and nothing under it; where
that block is a paragraph of a reference list's name in bold, as a paper brought in from Word
heads it; or where the section the list stands in is headed as a reference list. With `mg-references-live`
set, a manuscript with no `refs` div is given one at its end, where `zotero_word.lua` then puts
the bibliography field; without it, as after citeproc, a list that holds nothing gets no
heading. A `refs` div inside another block is the author's arrangement and is left as it is.

The heading is the build's, never the source's: it carries the bookmark `mg-references`, and a
document read back passes it over, so that `import` finds it in no paragraph of the source and
a document built before it compares as it did.
]]

local title = nil
local live = false

-- The heading's identifier, which the docx writer makes a bookmark: what tells the heading
-- this build added from one the author wrote, to `docxtext.blocks` as it reads a document
-- back (`docxtext.BUILT_HEADING`).
local BUILT = 'mg-references'

-- What a heading that already heads a reference list is called, its number taken off.
local NAMES = {
  'references?', 'reference list', 'list of references', 'bibliography', 'literature cited',
  'works cited', 'cited literature', 'literature',
}

local function decoded(hex)
  -- In parentheses: gsub also returns its count, which decode would take as an argument.
  return pandoc.json.decode((hex:gsub('..', function(pair)
    return string.char(tonumber(pair, 16))
  end)))
end

local function Meta(meta)
  local given = meta['mg-references-heading']
  live = meta['mg-references-live'] ~= nil
  meta['mg-references-heading'] = nil
  meta['mg-references-live'] = nil
  if given == nil then return meta end
  local ok, text = pcall(decoded, pandoc.utils.stringify(given))
  if not ok or type(text) ~= 'string' then
    error('references_heading.lua: the title of the reference list could not be read')
  end
  title = text
  return meta
end

local function folded(text)
  local plain = pandoc.text.lower(text)
  -- "6. References", "VI References", "References:"
  plain = plain:gsub('^%s*[%divxlc]+[.)]?%s+', ''):gsub('[%s:.]+$', ''):gsub('^%s+', '')
  return plain
end

local function names_a_list(header)
  local text = folded(pandoc.utils.stringify(header.content))
  if title ~= nil and text == folded(title) then return true end
  for _, name in ipairs(NAMES) do
    if text:match('^' .. name .. '$') then return true end
  end
  return false
end

-- A block the document does not print: an HTML comment, a fence for another format.
local function unprinted(block)
  return block.t == 'RawBlock' and block.format ~= 'openxml'
end

-- A paragraph that is only a reference list's name in bold or italics, as a paper brought in
-- from Word heads its list: "**References**".
-- The build's paragraph identifier is an empty span before the text (`roundtrip.tag`), and
-- is passed over.
local function labelled(block)
  if block.t ~= 'Para' and block.t ~= 'Plain' then return false end
  local shown = {}
  for _, inline in ipairs(block.content) do
    if not (inline.t == 'Span' and #inline.content == 0) then shown[#shown + 1] = inline end
  end
  if #shown ~= 1 or (shown[1].t ~= 'Strong' and shown[1].t ~= 'Emph') then return false end
  return names_a_list(shown[1])
end

local function headed(blocks, at)
  local before = at - 1
  while before >= 1 and unprinted(blocks[before]) do before = before - 1 end
  if before >= 1 and (blocks[before].t == 'Header' or labelled(blocks[before])) then
    return true
  end
  for index = at - 1, 1, -1 do
    if blocks[index].t == 'Header' then return names_a_list(blocks[index]) end
  end
  return false
end

local function Pandoc(doc)
  if FORMAT ~= 'docx' or title == nil then return nil end
  local blocks = doc.blocks
  local at = nil
  for index, block in ipairs(blocks) do
    if block.t == 'Div' and block.identifier == 'refs' then at = index end
  end
  if at == nil then
    local nested = false
    doc:walk({ Div = function(div)
      if div.identifier == 'refs' then nested = true end
    end })
    if nested or not live then return nil end
    blocks:insert(pandoc.Div({}, pandoc.Attr('refs')))
    at = #blocks
  elseif not live and #blocks[at].content == 0 then
    return nil
  end
  if not headed(blocks, at) then
    blocks:insert(at, pandoc.Header(1, pandoc.Inlines(title), pandoc.Attr(BUILT, { 'unnumbered' })))
  end
  doc.blocks = blocks
  return doc
end

return {
  { Meta = Meta },
  { Pandoc = Pandoc },
}
