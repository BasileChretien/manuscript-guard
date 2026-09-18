--[[
Word's half of what Better BibTeX's zotero.lua does for LibreOffice only.

Word's Zotero integration keeps a document's citation style in custom document properties
named ZOTERO_PREF_1, ZOTERO_PREF_2, ... (at most 255 characters each) and the reference list
in an `ADDIN ZOTERO_BIBL` field. zotero.lua writes both for .odt and neither for .docx, so
the Word document it built had live citations, no reference list, and asked for a style on
the first Refresh. An author who then used the Zotero tab in Word found nothing to update.

Run after zotero.lua on a docx build, this filter adds:

* the bibliography field where the manuscript writes `::: {#refs}` / `:::` (the div pandoc's
  citeproc fills in an offline build), or at the end of the document if there is none;
* the document preferences, when the metadata names a Zotero style:

      zotero-word:
        style: http://www.zotero.org/styles/apa
        locale: en-GB
        zotero-version: 9.0.6

  Without a style, Zotero asks for one on the first Refresh, as it does for any new document.
]]

local seen_refs = false

local BIBLIOGRAPHY = table.concat({
  '<w:p>',
  '<w:r><w:fldChar w:fldCharType="begin"/></w:r>',
  '<w:r><w:instrText xml:space="preserve"> ADDIN ZOTERO_BIBL ',
  '{"uncited":[],"omitted":[],"custom":[]} CSL_BIBLIOGRAPHY </w:instrText></w:r>',
  '<w:r><w:fldChar w:fldCharType="separate"/></w:r>',
  '<w:r><w:t>{Bibliography: in Word, open the Zotero tab and click Refresh}</w:t></w:r>',
  '<w:r><w:fldChar w:fldCharType="end"/></w:r>',
  '</w:p>',
})

local function xml_attr(text)
  return (text:gsub('&', '&amp;'):gsub('"', '&quot;'):gsub('<', '&lt;'):gsub('>', '&gt;'))
end

local function chunks(text, size)
  local parts = {}
  for start = 1, #text, size do
    parts[#parts + 1] = text:sub(start, start + size - 1)
  end
  return parts
end

local function preferences(style, locale, version, title)
  -- The session id only has to be stable for one document; derived from the title rather
  -- than random, so two builds of the same manuscript are the same file.
  local session = pandoc.utils.sha1(title or 'manuscript'):sub(1, 8)
  return table.concat({
    '<data data-version="3" zotero-version="', xml_attr(version), '">',
    '<session id="', session, '"/>',
    '<style id="', xml_attr(style), '" locale="', xml_attr(locale),
    '" hasBibliography="1" bibliographyStyleHasBeenSet="1"/>',
    '<prefs><pref name="fieldType" value="Field"/></prefs>',
    '</data>',
  })
end

function Meta(meta)
  if FORMAT ~= 'docx' then return nil end
  -- zotero.lua has read its settings by now. Left in the metadata, pandoc would write them
  -- to the .docx as a custom document property nobody asked for.
  meta.zotero = nil
  local word = meta['zotero-word']
  meta['zotero-word'] = nil
  if word == nil or word.style == nil then return meta end

  local style = pandoc.utils.stringify(word.style)
  local locale = word.locale and pandoc.utils.stringify(word.locale) or 'en-US'
  local version = word['zotero-version'] and pandoc.utils.stringify(word['zotero-version']) or '7.0'
  local title = meta.title and pandoc.utils.stringify(meta.title) or nil
  -- MetaString, not a string parsed as Markdown: pandoc writes unknown metadata to the .docx
  -- as custom document properties, and Markdown would mangle the XML.
  for i, part in ipairs(chunks(preferences(style, locale, version, title), 255)) do
    meta['ZOTERO_PREF_' .. i] = pandoc.MetaString(part)
  end
  return meta
end

function Div(div)
  if FORMAT ~= 'docx' or div.identifier ~= 'refs' then return nil end
  seen_refs = true
  return pandoc.RawBlock('openxml', BIBLIOGRAPHY)
end

function Pandoc(doc)
  if FORMAT ~= 'docx' or seen_refs then return nil end
  doc.blocks:insert(pandoc.RawBlock('openxml', BIBLIOGRAPHY))
  return doc
end

return {
  { Meta = Meta },
  { Div = Div },
  { Pandoc = Pandoc },
}
