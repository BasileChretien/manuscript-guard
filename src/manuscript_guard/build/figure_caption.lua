--[[
A figure's caption, styled as a caption.

A caption written as an ordinary paragraph is set in the body font, and on the page there is
nothing to tell a reader where the caption ends and the argument resumes. The journal's own
typesetting will do this; the author reading a draft, and the co-author reading the .docx,
get it here.

The caption of a figure is the paragraph that follows it: a paragraph whose text begins
"Figure 1.", "Figure 2." and so on, directly after the figure it belongs to. That is the
convention the manuscript already follows, and this filter only reads it — a paragraph that
does not follow a figure is left alone, whatever it says, and so is a figure whose next
paragraph is prose.

The paragraph is wrapped in a div carrying `custom-style`, which pandoc's docx writer turns
into a paragraph style. The style itself is defined in the reference document the build
generates (`build/styles.py`); nothing here chooses a size.
]]

local STYLE = 'Figure Caption'

-- Whitespace, and the empty span a marked build puts in front of a paragraph as its
-- identifier: nothing a reader sees.
local function ignorable(inline)
  return inline.t == 'Space'
    or inline.t == 'SoftBreak'
    or (inline.t == 'Span' and #inline.content == 0)
end

local function is_figure(block)
  -- pandoc 3 reads an image with a caption as a Figure; an image alone in a paragraph,
  -- which is what a figure binding expands to, stays a Para holding one Image.
  if block.t == 'Figure' then
    return true
  end
  if block.t ~= 'Para' then
    return false
  end
  local images = 0
  for _, inline in ipairs(block.content) do
    if inline.t == 'Image' then
      images = images + 1
    elseif not ignorable(inline) then
      return false
    end
  end
  return images == 1
end

local function is_caption(block)
  if block.t ~= 'Para' then
    return false
  end
  local text = pandoc.utils.stringify(block)
  return text:match('^Figure%s+%d') ~= nil
end

function Blocks(blocks)
  local out = pandoc.List()
  local after_figure = false
  for _, block in ipairs(blocks) do
    if after_figure and is_caption(block) then
      out:insert(pandoc.Div({ block }, pandoc.Attr('', {}, { { 'custom-style', STYLE } })))
    else
      out:insert(block)
    end
    after_figure = is_figure(block)
  end
  return out
end
