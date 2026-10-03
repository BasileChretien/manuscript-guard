--[[
A figure's caption, styled as a caption.

A caption written as an ordinary paragraph is set in the body font, and on the page there is
nothing to tell a reader where the caption ends and the argument resumes. The journal's own
typesetting will do this; the author reading a draft, and the co-author reading the .docx,
get it here.

The caption of a figure is the paragraph that follows it: a paragraph whose text begins
"Figure 1.", "Figure 2:", "Figure S1." and so on, directly after the figure it belongs to.
That is the convention the manuscript already follows, and this filter only reads it — a
paragraph that does not follow a figure is left alone, whatever it says, and so is a figure
whose next paragraph is prose.

The number has to end at the full stop or colon, because the argument resumes under a figure
as often as a caption opens there: "Figure 1 shows the estimate ..." and "Figure 2.5-fold
higher ..." are prose, and restyling them would be the whole point of the rule lost.

The paragraph is wrapped in a div carrying `custom-style`, which pandoc's docx writer turns
into a paragraph style. The style itself is defined in the reference document the build
generates (`build/styles.py`); nothing here chooses a size.
]]

local STYLE = 'Figure Caption'

-- Whitespace, plus the two bytes U+00A0 is in UTF-8: a Lua pattern class matches bytes.
local SPACE_CLASS = '[%s\194\160]'

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
  -- The trailing space lets one pattern cover a caption that is only "Figure 1." as well as
  -- one that goes on, and the %s after the stop is what keeps "Figure 2.5-fold" out.
  local text = pandoc.utils.stringify(block) .. ' '
  -- SPACE_CLASS, not %s: Lua patterns know nothing of U+00A0, and a caption pasted from Word
  -- or typeset by pandoc after an abbreviation has a no-break space where a space was typed.
  return text:match('^Figure' .. SPACE_CLASS .. '+S?%d+[%.:]' .. SPACE_CLASS) ~= nil
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
