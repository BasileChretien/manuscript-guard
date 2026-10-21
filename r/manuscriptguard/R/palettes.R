#' The palettes manuscript-guard ships
#'
#' The colours are other people's: MetBrewer, MoMAColors, NatParksPalettes, PNWColors and
#' wesanderson, palettes drawn from paintings, photographs and films; Okabe and Ito's eight;
#' ColorBrewer's schemes; viridis and its family; cividis; and Fabio Crameri's scientific
#' colour maps. `tools/derive_palettes.py` reads each from its collection's own file, with
#' what manuscript-guard's colour check says of it, into `palettes.json`, the same file the
#' Python package reads. Each collection's licence and notice are in that file and in the
#' repository's ATTRIBUTION.md.
#'
#' @return A data frame, one row a palette: its name, collection, kind as the collection
#'   states it (NA where it states none), number of colours, the most of them distinct for
#'   every reader with a colour-vision deficiency (NA for a continuous map), whether its
#'   lightness runs one way, turns once or neither, whether each deficiency keeps that, and
#'   whether its collection calls it colour-blind friendly.
#' @export
mg_palettes <- function() {
  held <- mg_palette_data()$palettes
  data.frame(
    name = names(held),
    collection = vapply(held, function(p) p$collection, ""),
    kind = vapply(held, function(p) if (is.null(p$kind)) NA_character_ else p$kind, ""),
    colours = vapply(held, function(p) length(p$colours), 0L),
    distinct_cvd = vapply(held, function(p) {
      if (is.null(p$distinct$cvd)) NA_integer_ else as.integer(p$distinct$cvd)
    }, 0L),
    lightness = vapply(held, function(p) p$lightness, ""),
    lightness_kept = vapply(held, function(p) isTRUE(p$lightness_kept), TRUE),
    claims_cvd = vapply(held, function(p) {
      if (is.null(p$claims_cvd)) NA else isTRUE(p$claims_cvd)
    }, TRUE),
    row.names = NULL,
    stringsAsFactors = FALSE
  )
}

#' Colours of a palette, by name
#'
#' Of a set of colours, the `n` its collection gives for that many: ColorBrewer's own scheme
#' of `n`, or the colours whose rank in the collection's order is at most `n`, in the
#' palette's sequence, as MetBrewer, MoMAColors, NatParksPalettes and PNWColors give them,
#' or the first `n`. More than it has is refused: ask for `type = "continuous"`, which
#' interpolates, and whose colours are no longer as far apart. Of a continuous map, `n`
#' evenly spaced along it. The same colours as Python's `manuscript_guard.palettes.colours`.
#'
#' @param name The palette's name, `"met/Archambault"`, or its last part, `"Archambault"`,
#'   where only one collection has a palette of that name.
#' @param n How many colours; all of them where NULL.
#' @param type `"discrete"`, or `"continuous"` to interpolate `n` colours along it.
#' @param reverse Whether to give them last first.
#' @return A character vector of hex codes.
#' @export
mg_palette <- function(name, n = NULL, type = c("discrete", "continuous"), reverse = FALSE) {
  type <- match.arg(type)
  found <- mg_find_palette(name)
  colours <- unlist(found$colours)
  continuous <- length(colours) >= 64 && !identical(found$kind, "qualitative")
  if (is.null(n)) {
    chosen <- colours
  } else if (n < 1) {
    stop("a palette of ", n, " colours", call. = FALSE)
  } else if (type == "continuous" || continuous) {
    chosen <- tolower(grDevices::colorRampPalette(colours)(n))
  } else {
    chosen <- mg_discrete(found, colours, n)
  }
  if (reverse) rev(chosen) else chosen
}

#' A ggplot2 colour or fill scale of a palette
#'
#' @param name The palette's name, as `mg_palette` takes it.
#' @param discrete Whether the variable is discrete; a continuous one gets a gradient
#'   through the palette's colours.
#' @param reverse Whether to give the colours last first.
#' @param ... Passed to the ggplot2 scale.
#' @export
scale_colour_mg <- function(name, discrete = TRUE, reverse = FALSE, ...) {
  mg_scale("colour", name, discrete, reverse, ...)
}

#' @rdname scale_colour_mg
#' @export
scale_fill_mg <- function(name, discrete = TRUE, reverse = FALSE, ...) {
  mg_scale("fill", name, discrete, reverse, ...)
}

#' A ggplot2 theme sized to the target journal's artwork rules
#'
#' Reads the profile of the journal `paper.yaml` names (`profiles/journals/<name>.yaml`, the
#' project's own) for the smallest text and the thinnest line it prints, and returns `base`
#' at a size no smaller: 7 pt where the journal's least is lower, a size many artwork guides
#' give for a figure's text at print size, or `size` where it is given.
#'
#' @param root The project, found upwards from the working directory where NULL.
#' @param base A ggplot2 theme function, `ggplot2::theme_classic` by default.
#' @param size The text size in points, where the journal's least should not decide it.
#' @return A ggplot2 theme.
#' @export
mg_theme <- function(root = NULL, base = ggplot2::theme_classic, size = NULL) {
  rules <- mg_figure_rules(root)
  least <- if (is.null(rules$min_text_pt)) 0 else rules$min_text_pt
  size <- if (is.null(size)) max(7, least) else size
  line <- max(0.5, if (is.null(rules$min_line_pt)) 0 else rules$min_line_pt)
  base(base_size = size) +
    ggplot2::theme(line = ggplot2::element_line(linewidth = line / ggplot2::.pt))
}

#' The width and height a figure prints at, in inches, for `ggplot2::ggsave`
#'
#' @param width `"single"` for the journal's narrowest width, `"double"` for its widest, or
#'   a number of millimetres.
#' @param ratio The height over the width.
#' @param root The project, found upwards from the working directory where NULL.
#' @return A named numeric vector, `width` and `height` in inches.
#' @export
mg_figure_size <- function(width = "single", ratio = 0.62, root = NULL) {
  mm <- if (is.numeric(width)) width else {
    widths <- unlist(mg_figure_rules(root)$widths_mm)
    if (length(widths) == 0) {
      stop("the journal's profile gives no widths_mm; pass a width in mm", call. = FALSE)
    }
    if (identical(width, "double")) max(widths) else min(widths)
  }
  c(width = mm / 25.4, height = mm / 25.4 * ratio)
}

# -------------------------------------------------------------------------------- inside

mg_palette_data <- function() {
  path <- getOption(
    "manuscriptguard.palettes",
    system.file("extdata", "palettes.json", package = "manuscriptguard")
  )
  if (!nzchar(path) || !file.exists(path)) {
    stop("the palettes file is not installed with the package", call. = FALSE)
  }
  jsonlite::fromJSON(path, simplifyVector = FALSE)
}

mg_find_palette <- function(name) {
  held <- mg_palette_data()$palettes
  if (!is.null(held[[name]])) {
    return(held[[name]])
  }
  short <- vapply(strsplit(names(held), "/", fixed = TRUE), function(p) tolower(p[length(p)]), "")
  found <- names(held)[short == tolower(name)]
  if (length(found) == 1) {
    return(held[[found]])
  }
  if (length(found) > 1) {
    stop(length(found), " palettes are called '", name, "': ", paste(found, collapse = ", "),
         call. = FALSE)
  }
  stop("no palette is called '", name, "'; mg_palettes() lists them", call. = FALSE)
}

mg_discrete <- function(found, colours, n) {
  if (n > length(colours)) {
    stop(found$collection, " palette has ", length(colours), " colours, and ", n,
         " were asked for; type = 'continuous' interpolates more", call. = FALSE)
  }
  by_n <- found$by_n
  if (!is.null(by_n)) {
    own <- by_n[[as.character(n)]]
    if (!is.null(own)) {
      return(unlist(own))
    }
    smallest <- by_n[[as.character(min(as.integer(names(by_n))))]]
    return(unlist(smallest)[seq_len(n)])
  }
  if (!is.null(found$order)) {
    return(colours[unlist(found$order) <= n])
  }
  colours[seq_len(n)]
}

mg_scale <- function(aesthetic, name, discrete, reverse, ...) {
  if (!requireNamespace("ggplot2", quietly = TRUE)) {
    stop("ggplot2 is needed for a scale", call. = FALSE)
  }
  if (discrete) {
    return(ggplot2::discrete_scale(
      aesthetics = aesthetic,
      palette = function(n) mg_palette(name, n, reverse = reverse),
      ...
    ))
  }
  gradient <- mg_palette(name, 256, type = "continuous", reverse = reverse)
  if (aesthetic == "colour") {
    ggplot2::scale_colour_gradientn(colours = gradient, ...)
  } else {
    ggplot2::scale_fill_gradientn(colours = gradient, ...)
  }
}

mg_figure_rules <- function(root = NULL) {
  if (!requireNamespace("yaml", quietly = TRUE)) {
    stop("the yaml package is needed to read the journal's profile", call. = FALSE)
  }
  root <- if (is.null(root)) mg_find_root() else root
  paper <- yaml::read_yaml(file.path(root, "paper.yaml"))
  slug <- paper$target_journal
  if (is.null(slug)) {
    stop("paper.yaml names no target_journal", call. = FALSE)
  }
  profile <- file.path(root, "profiles", "journals", paste0(slug, ".yaml"))
  if (!file.exists(profile)) {
    stop("no profile at ", profile, call. = FALSE)
  }
  rules <- yaml::read_yaml(profile)$figures
  if (is.null(rules)) list() else rules
}
