--[[
A heading over the reference list of the Word document.

pandoc's citeproc puts the reference list where the manuscript writes `::: {#refs}` / `:::`, or
at the end, with no heading of its own unless `reference-section-title` is set, and that
setting is passed over where the manuscript has a `refs` div. A live build's bibliography
field goes in the same place (`zotero_word.lua`). So a manuscript that did not end with its
own "# References" built into a document whose references followed the last statement as if
they were part of it.

Run before citeproc on an offline build, and before `zotero_word.lua` on a live one, this
filter first gives the list its place where the manuscript writes no `refs` div: under the
author's own last heading of a reference list with nothing printed under it before the next
heading of its level or above (the end of main.md in a paper of several files, where the next
opens with a heading), or else at the end. It then puts a first-level heading, unnumbered,
before the list, titled as the `mg-references-heading` metadata says: JSON written in
hexadecimal, as `narrative.lua` takes its names, so that the command line carries any title.
It adds none where the author wrote one: where the block before the list, comments aside, is
a heading, or a paragraph of only a reference list's name in bold or in italics, as a paper
brought in from Word heads its list ("**References**", "*Bibliographie*"); or where the
section the list stands in is headed as a reference list. A `refs` div inside another block
is the author's arrangement and is left as it is. On an offline build, which the
`mg-references-citeproc` metadata says, a document whose metadata sets `suppress-bibliography`
as citeproc reads it (true, or the word "true" or "yes"), for which citeproc prints no list,
gets no heading; a live build's field prints the list whatever it says.

The heading is the build's, never the source's: it carries the bookmark `mg-references`, and a
document read back passes it over, so that `import` finds it in no paragraph of the source and
a document built before it compares as it did.
]]

local title = nil

-- The heading's bookmark, an empty span at its start: what tells the heading this build
-- added from one the author wrote, to `docxtext.blocks` as it reads a document back, and to
-- the marked-up copy (`docxtext.BUILT_HEADING`).
local BUILT = 'mg-references'

-- What a heading that already heads a reference list is called, its number taken off, in
-- English and in the languages a paper brought in from Word is most often headed in. Not
-- "literature" alone, which names a section of an outline as often.
local NAMES = {
  'references?', 'reference list', 'list of references', 'references and notes',
  'bibliography', 'literature cited', 'works cited', 'cited literature',
  'références', 'bibliographie', 'literaturverzeichnis', 'literatur', 'referencias',
  'bibliografía', 'riferimenti', 'riferimenti bibliografici', 'bibliografia', 'referências',
}

-- A section's number, in the forms headings are numbered: "(7)", "7", "7.", "7.1", "6.2.",
-- "7)", "VI", "VI.", "iv)", "A.", "b)". The first that matches is taken off.
local NUMBERS = {
  '^%(%w+%)%s+',
  '^%d+[%.%d]*[.)]?%s+',
  '^[ivxlcdm]+[.)]?%s+',
  '^%a[.)]%s+',
}

local function decoded(hex)
  -- In parentheses: gsub also returns its count, which decode would take as an argument.
  return pandoc.json.decode((hex:gsub('..', function(pair)
    return string.char(tonumber(pair, 16))
  end)))
end

-- `suppress-bibliography` as citeproc reads it: true, or the word "true" or "yes".
local function suppressed(value)
  if value == nil or type(value) == 'boolean' then return value == true end
  local said = pandoc.utils.stringify(value)
  return said == 'true' or said == 'yes'
end

local function Meta(meta)
  local given = meta['mg-references-heading']
  local citeproc = meta['mg-references-citeproc'] ~= nil
  meta['mg-references-heading'] = nil
  meta['mg-references-citeproc'] = nil
  if given == nil or (citeproc and suppressed(meta['suppress-bibliography'])) then
    return meta
  end
  local ok, text = pcall(decoded, pandoc.utils.stringify(given))
  if not ok or type(text) ~= 'string' then
    error('references_heading.lua: the title of the reference list could not be read')
  end
  title = text
  return meta
end

local function folded(text)
  local plain = pandoc.text.lower(text):gsub('^%s+', '')
  for _, number in ipairs(NUMBERS) do
    local without, taken = plain:gsub(number, '', 1)
    if taken > 0 then
      plain = without
      break
    end
  end
  return (plain:gsub('[%s:.]+$', ''))
end

local function names_a_list(header)
  local text = folded(pandoc.utils.stringify(header.content))
  if title ~= nil and text == folded(title) then return true end
  for _, name in ipairs(NAMES) do
    if text:match('^' .. name .. '$') then return true end
  end
  return false
end

-- A block the document does not print: an HTML comment, a fence for another format, and the
-- empty div the build puts between two files (`document._BETWEEN_FILES`).
local function unprinted(block)
  if block.t == 'Div' then return #block.content == 0 and block.identifier == '' end
  return block.t == 'RawBlock' and block.format ~= 'openxml'
end

-- A paragraph that is only a reference list's name in bold or in italics. The build's
-- paragraph identifier is an empty span before the text (`roundtrip.tag`), and is passed over.
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

-- The last heading of a reference list that has nothing under it before the next heading of
-- its level or above, comments aside: where the author meant the list to go.
local function waiting(blocks)
  local found = nil
  for index, block in ipairs(blocks) do
    if block.t == 'Header' and names_a_list(block) then
      local after = index + 1
      while after <= #blocks and unprinted(blocks[after]) do after = after + 1 end
      local next = blocks[after]
      if next == nil or (next.t == 'Header' and next.level <= block.level) then
        found = index
      end
    end
  end
  return found
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
    if nested then return nil end
    local under = waiting(blocks)
    if under ~= nil then
      blocks:insert(under + 1, pandoc.Div({}, pandoc.Attr('refs')))
      doc.blocks = blocks
      return doc
    end
    blocks:insert(pandoc.Div({}, pandoc.Attr('refs')))
    at = #blocks
  end
  if not headed(blocks, at) then
    -- The bookmark as the build writes a paragraph's identifier: an empty span with the id,
    -- which the docx writer makes a bookmark; a heading's own identifier it does not.
    local inlines = pandoc.Inlines({ pandoc.Span({}, pandoc.Attr(BUILT)) })
    inlines:extend(pandoc.Inlines(title))
    blocks:insert(at, pandoc.Header(1, inlines, pandoc.Attr('', { 'unnumbered' })))
  end
  doc.blocks = blocks
  return doc
end

return {
  { Meta = Meta },
  { Pandoc = Pandoc },
}
