# The data profile: the Python `vault/profile.py`, rule for rule, for `em$profile`. What it
# writes of a table the script read leaves the vault only when a person releases it, and
# `vault synthesize` draws the synthetic copy from it alone. Both languages write the same
# bytes of the same table: tests/data/profile holds them to it. Numbers are written as C's
# `%.6g` writes them.

mg_profile_schema <- "manuscript-guard/data-profile/1"
mg_profile_centiles <- c(5L, 10L, 25L, 50L, 75L, 90L, 95L)
mg_profile_most_levels <- 50L
mg_profile_fewest_for_mean <- 3L
mg_profile_most_decimals <- 6L
mg_profile_read_as <- c("delimiter", "decimal", "encoding", "quoting", "newline", "dates",
                        "header_of")
mg_profile_delimiters <- c(",", ";", "\t", "|")
mg_profile_directives <- c(Y = 4L, m = 2L, d = 2L, H = 2L, M = 2L, S = 2L)
mg_profile_held <- "held back: its counts would give a count below the minimum away"
mg_profile_mark <- intToUtf8(0xFEFF)

# What the JSON is made of: an object, an array, a number written as it is, and null.
mg_obj <- function(...) structure(list(...), class = "mg_obj")
mg_arr <- function(items) structure(unname(items), class = "mg_arr")
mg_fig <- function(x) structure(sprintf("%.6g", x + 0), class = "mg_fig")
mg_null <- structure(list(), class = "mg_null")

mg_profile_check_name <- function(name) {
  if (!is.character(name) || length(name) != 1 || is.na(name) || !nzchar(trimws(name)) ||
      name != trimws(name)) {
    stop("profile: give the file's name in the vault, \"cohort.csv\"", call. = FALSE)
  }
  parts <- strsplit(name, "/", fixed = TRUE)[[1]]
  if (grepl("[\\\\:]", name) || startsWith(name, "/") || endsWith(name, "/") ||
      any(parts %in% c("", ".", ".."))) {
    stop("profile: name ", name, " is not a file's name in the vault: a relative path with ",
         "forward slashes, no `..`", call. = FALSE)
  }
  name
}

# ------------------------------------------------------------------- how the file was read

# A date format of %Y %m %d %H %M %S and other characters, as a pattern and the directive
# each of its groups holds; any other directive is refused.
mg_profile_format_pattern <- function(form) {
  chars <- strsplit(form, "", fixed = TRUE)[[1]]
  pattern <- character()
  groups <- character()
  at <- 1L
  while (at <= length(chars)) {
    char <- chars[at]
    if (char != "%") {
      pattern <- c(pattern, if (grepl("[A-Za-z0-9 ]", char)) char else paste0("\\Q", char, "\\E"))
      at <- at + 1L
      next
    }
    code <- if (at < length(chars)) chars[at + 1L] else ""
    if (code == "%") {
      pattern <- c(pattern, "%")
    } else if (code %in% names(mg_profile_directives)) {
      if (code %in% groups) stop("profile: date format ", form, " names %", code, " twice",
                                 call. = FALSE)
      pattern <- c(pattern, sprintf("([0-9]{%d})", mg_profile_directives[[code]]))
      groups <- c(groups, code)
    } else {
      stop("profile: date format ", form, ": only %Y, %m, %d, %H, %M, %S and %% are read",
           call. = FALSE)
    }
    at <- at + 2L
  }
  if (!all(c("Y", "m", "d") %in% groups)) {
    stop("profile: date format ", form, " holds no %Y, %m and %d", call. = FALSE)
  }
  list(pattern = paste0("^", paste(pattern, collapse = ""), "$"), groups = groups)
}

# What the header line of the file says of its shape: the delimiter most often in it, a
# byte-order mark, the line ending. Nothing after the header is read.
mg_profile_sniffed <- function(path) {
  con <- file(path, "rb")
  on.exit(close(con))
  bytes <- readBin(con, "raw", n = 1048576L)
  end <- which(bytes == as.raw(10L))
  line <- if (length(end)) bytes[seq_len(end[1])] else bytes
  found <- list()
  crlf <- length(line) >= 2 && line[length(line)] == as.raw(10L) &&
    line[length(line) - 1L] == as.raw(13L)
  found$newline <- if (crlf) "\r\n" else "\n"
  if (length(line) >= 3 && identical(line[1:3], as.raw(c(0xef, 0xbb, 0xbf)))) {
    found$encoding <- "utf-8-sig"
  }
  counts <- vapply(mg_profile_delimiters, function(d) sum(line == charToRaw(d)), numeric(1))
  if (max(counts) > 0) found$delimiter <- mg_profile_delimiters[which.max(counts)]
  found
}

mg_profile_suffix <- function(name) {
  base <- basename(name)
  dots <- gregexpr(".", base, fixed = TRUE)[[1]]
  last <- if (dots[1] == -1L) 0L else max(dots)
  if (last <= 1L || last == nchar(base)) return("")
  tolower(substring(base, last + 1L))
}

# The file's shape, for the synthetic copy, and the date format of each column given one.
mg_profile_shape <- function(name, read_as) {
  given <- if (is.null(read_as)) list() else as.list(read_as)
  unknown <- setdiff(names(given), mg_profile_read_as)
  if (length(unknown)) {
    stop("profile: read_as says ", paste(sort(unknown, method = "radix"), collapse = ", "),
         "; it may say ",
         paste(mg_profile_read_as, collapse = ", "), call. = FALSE)
  }
  form <- mg_profile_suffix(name)
  shape <- list(format = form, delimiter = if (form %in% c("tsv", "tab")) "\t" else ",",
                decimal = ".", encoding = "utf-8", quoting = "minimal", newline = "\n")
  if (!is.null(given$header_of)) {
    sniffed <- mg_profile_sniffed(given$header_of)
    shape[names(sniffed)] <- sniffed
  }
  for (key in intersect(names(shape), names(given))) shape[[key]] <- given[[key]]
  fits <- list(
    delimiter = function(v) is.character(v) && nchar(v) == 1 && !grepl("[\r\n\".]", v),
    decimal = function(v) identical(v, ".") || identical(v, ","),
    encoding = function(v) is.character(v) && nzchar(v),
    quoting = function(v) isTRUE(v %in% c("minimal", "all")),
    newline = function(v) isTRUE(v %in% c("\n", "\r\n"))
  )
  for (key in names(fits)) {
    if (!fits[[key]](shape[[key]])) {
      stop("profile: read_as ", key, " ", shape[[key]], " is not one this reads", call. = FALSE)
    }
  }
  shape$bom <- gsub("_", "-", tolower(shape$encoding), fixed = TRUE) %in%
    c("utf-8-sig", "utf8-sig")
  if (shape$bom) shape$encoding <- "utf-8"
  dates <- if (is.null(given$dates)) list() else as.list(given$dates)
  if (length(dates) && (is.null(names(dates)) ||
                        !all(vapply(dates, is.character, logical(1))))) {
    stop("profile: read_as dates maps a column's name to its date format", call. = FALSE)
  }
  for (form_ in dates) mg_profile_format_pattern(form_)
  list(shape = shape, dates = dates)
}

# ------------------------------------------------------------------------- reading a value

# Each value of a date or date and time column, as its ISO date (and time); NA where it does
# not read.
mg_profile_by_format <- function(x, form, kind) {
  if (!is.character(x) && !is.factor(x)) {
    return(if (kind == "date") mg_date_of(x) else mg_datetime_of(x))
  }
  x <- as.character(x)
  spec <- mg_profile_format_pattern(form)
  parts <- mg_parts(x, spec$pattern, length(spec$groups))
  colnames(parts) <- spec$groups
  get <- function(code) if (code %in% spec$groups) parts[, code] else rep("00", length(x))
  day <- mg_calendar(parts[, "Y"], parts[, "m"], parts[, "d"])
  if (kind == "date") return(day)
  clock <- mg_clock(get("H"), get("M"), get("S"))
  ifelse(is.na(day) | is.na(clock), NA_character_, paste0(day, "T", clock))
}

mg_profile_date_reader <- function(x, kind, form) {
  if (!is.null(form)) return(mg_profile_by_format(x, form, kind))
  if (kind == "date") mg_date_of(x) else mg_datetime_of(x)
}

# The type a column's values are, where the dictionary does not say.
mg_profile_type_read <- function(present, form) {
  if (!length(present)) return("text")
  if (!is.null(form)) return(if (grepl("%H", form, fixed = TRUE)) "datetime" else "date")
  if (all(!is.na(mg_number_of(present)))) return("continuous")
  if (all(!is.na(mg_date_of(present)))) return("date")
  if (all(!is.na(mg_datetime_of(present)))) return("datetime")
  if (all(!is.na(mg_time_of(present)))) return("time")
  "text"
}

mg_profile_kind <- function(entry, kind, texts) {
  if (!is.null(entry)) {
    if (kind %in% mg_quality_coded) return("levels")
    if (kind %in% mg_quality_numeric) return("number")
    if (kind %in% c("date", "datetime")) return("date")
    if (kind == "time") return("time")
    return("withheld")
  }
  distinct <- length(unique(texts))
  if (distinct == length(texts)) return("withheld")
  if (kind %in% c("date", "datetime")) return("date")
  if (distinct <= mg_profile_most_levels) return("levels")
  if (kind == "continuous") return("number")
  if (kind == "time") return("time")
  "withheld"
}

# --------------------------------------------------------------------- counts and margins
#
# What a reader can work out of a column's counts, as the Python `vault/disclosure.py`: a count
# printed is itself; "<m" one to m - 1, since nought is printed as 0; one held beside, the
# minimum or more, at most each count printed after it and below each printed before it; and
# what the rest of the column says (a cell's `least` and `most`). Every choice is made from
# what is printed: one count is held beside where any is held behind the minimum, and where a
# count is still worked out the column's counts are withheld.

mg_profile_shown <- function(count, minimum) {
  held <- mg_held_back(count, minimum)
  if (is.null(held)) as.integer(count) else held
}

mg_profile_cell <- function(count, shown, least = 0, most = Inf, hidden = FALSE) {
  list(count = count, shown = shown, least = least, most = most, hidden = hidden)
}

mg_profile_printed <- function(cell) is.numeric(cell$shown) && !cell$hidden

mg_profile_known <- function(cell, total, minimum) {
  if (mg_profile_printed(cell)) return(c(as.numeric(cell$shown), as.numeric(cell$shown)))
  range <- if (is.null(cell$shown)) c(0, as.numeric(total)) else c(1, as.numeric(minimum) - 1)
  c(max(range[1], cell$least), min(range[2], cell$most))
}

mg_profile_ranges <- function(cells, total, minimum) {
  own <- lapply(cells, mg_profile_known, total = total, minimum = minimum)
  lows <- sum(vapply(own, function(r) r[1], numeric(1)))
  highs <- sum(vapply(own, function(r) r[2], numeric(1)))
  lapply(own, function(r) c(max(r[1], total - (highs - r[2])), min(r[2], total - (lows - r[1]))))
}

mg_profile_unsafe <- function(cells, total, minimum) {
  ranges <- mg_profile_ranges(cells, total, minimum)
  for (at in seq_along(cells)) {
    cell <- cells[[at]]
    range <- ranges[[at]]
    if (mg_profile_printed(cell) || range[1] != range[2]) next
    if (!cell$hidden || (range[1] >= 1 && range[1] < minimum)) return(TRUE)
  }
  FALSE
}

mg_profile_beside_bounds <- function(cells, chosen, minimum) {
  most <- Inf
  for (at in seq_along(cells)) {
    cell <- cells[[at]]
    if (at != chosen && mg_profile_printed(cell) && cell$shown > 0) {
      most <- min(most, if (at < chosen) cell$shown - 1 else cell$shown)
    }
  }
  c(as.numeric(minimum), most)
}

mg_profile_beside <- function(cells, minimum) {
  if (!any(vapply(cells, function(cell) is.character(cell$shown), logical(1)))) return(cells)
  candidates <- which(vapply(cells, function(cell) {
    mg_profile_printed(cell) && cell$count > 0
  }, logical(1)))
  if (!length(candidates)) return(cells)
  counts <- vapply(cells[candidates], function(cell) as.numeric(cell$count), numeric(1))
  chosen <- candidates[which.min(counts)]
  bounds <- mg_profile_beside_bounds(cells, chosen, minimum)
  held <- cells[[chosen]]
  held$shown <- NULL
  held["shown"] <- list(NULL)
  held$least <- max(held$least, bounds[1])
  held$most <- min(held$most, bounds[2])
  cells[[chosen]] <- held
  cells
}

mg_profile_json_count <- function(one) if (is.null(one)) mg_null else one

mg_profile_missing <- function(missing, shown, rows, minimum) {
  out <- list(missing = mg_profile_json_count(shown))
  if (is.numeric(shown) && missing >= minimum && missing > 0 && !is.null(rows) && rows > 0) {
    out$missing_share <- mg_fig(missing / rows)
  }
  out
}

mg_profile_held_view <- function() {
  list(kind = "withheld", missing = mg_null, held = mg_profile_held)
}

# --------------------------------------------------------------------------- the columns

mg_profile_decimals <- function(present) {
  text <- if (is.character(present)) mg_trim(present) else mg_text_of(present)
  found <- regmatches(text, regexec("^[+-]?[0-9]*[.]([0-9]+)$", text, perl = TRUE))
  places <- vapply(found, function(m) if (length(m)) nchar(m[2]) else 0L, integer(1))
  seen <- table(places)
  most <- max(seen)
  min(max(as.integer(names(seen)[seen == most])), mg_profile_most_decimals)
}

mg_profile_enough <- function(below, above, minimum) below >= minimum && above >= minimum

mg_profile_centiles_of <- function(values, minimum, show) {
  ordered <- sort(values, method = "radix")
  n <- length(ordered)
  found <- list()
  if (!n) return(structure(found, class = "mg_obj"))
  for (centile in mg_profile_centiles) {
    value <- ordered[mg_profile_centile_index(centile, n) + 1]
    below <- sum(ordered < value)
    above <- sum(ordered > value)
    if (mg_profile_enough(below, above, minimum)) found[[as.character(centile)]] <- show(value)
  }
  structure(found, class = "mg_obj")
}

# The place, from nought, of the centile's value among `n` sorted, in doubles: an integer
# product passes R's integers past some 22 million rows.
mg_profile_centile_index <- function(centile, n) {
  (as.numeric(centile) * as.numeric(n) + 99) %/% 100 - 1
}

# The fewest rows a centile is given of: `minimum` below its value and as many above.
mg_profile_fewest_rows <- function(centile, minimum) {
  n <- 2 * minimum + 1
  repeat {
    at <- mg_profile_centile_index(centile, n)
    if (mg_profile_enough(at, n - at - 1, minimum)) return(n)
    n <- n + 1
  }
}

mg_profile_month <- function(iso) {
  as.integer(substr(iso, 1, 4)) * 12L + as.integer(substr(iso, 6, 7)) - 1L
}

mg_profile_month_shown <- function(month) sprintf("%04d-%02d", month %/% 12L, month %% 12L + 1L)

# What the rest of a column's profile says of its rows read, where they are not printed, as
# the Python `_n_bounds`: decimals and centiles; a mean is not printed beside rows held back.
mg_profile_n_bounds <- function(out, minimum, number) {
  least <- 0
  most <- Inf
  if (number) {
    if (!is.null(out$decimals)) least <- minimum else most <- minimum - 1
  }
  for (centile in names(out$centiles)) {
    least <- max(least, mg_profile_fewest_rows(as.integer(centile), minimum))
  }
  c(least, most)
}

mg_profile_distribution <- function(column, rows, minimum) {
  present <- column$present
  if (column$role == "number") {
    read <- mg_number_of(present)
  } else if (column$role == "date") {
    read <- mg_profile_month(mg_profile_date_reader(present, column$kind, column$form))
  } else {
    read <- as.integer(substr(mg_time_of(present), 1, 2))
  }
  ok <- !is.na(read)
  values <- read[ok]
  out <- list()
  if (column$role == "number") {
    if (length(values) >= max(minimum, mg_profile_fewest_for_mean)) {
      mean <- sum(values) / length(values)
      out$mean <- mg_fig(mean)
      out$sd <- mg_fig(sqrt(sum((values - mean)^2) / (length(values) - 1)))
    }
    if (length(values) >= minimum && length(values)) {
      out$decimals <- if (column$kind == "count") 0L else mg_profile_decimals(present[ok])
    }
    out$centiles <- mg_profile_centiles_of(values, minimum, mg_fig)
  } else if (column$role == "date") {
    out$centiles <- mg_profile_centiles_of(values, minimum, mg_profile_month_shown)
  } else {
    out$centiles <- mg_profile_centiles_of(values, minimum, function(h) sprintf("%02d:00", h))
  }
  bounds <- mg_profile_n_bounds(out, minimum, column$role == "number")
  counts <- c(column$missing, sum(!ok), sum(ok))
  cells <- list(mg_profile_cell(counts[1], mg_profile_shown(counts[1], minimum)),
                mg_profile_cell(counts[2], mg_profile_shown(counts[2], minimum)),
                mg_profile_cell(counts[3], mg_profile_shown(counts[3], minimum),
                                bounds[1], bounds[2]))
  cells <- mg_profile_beside(cells, minimum)
  # A mean and SD only beside the rows read printed, as the Python `_stats_printed`: a total
  # over a held n would give it back.
  if (!is.numeric(cells[[3]]$shown)) {
    out$mean <- NULL
    out$sd <- NULL
  }
  if (mg_profile_unsafe(cells, rows, minimum)) return(mg_profile_held_view())
  c(mg_profile_missing(column$missing, cells[[1]]$shown, rows, minimum),
    list(unread = mg_profile_json_count(cells[[2]]$shown),
         n = mg_profile_json_count(cells[[3]]$shown)), out)
}

# How many levels "other" is said to fold, as the Python `_folded_said`.
mg_profile_folded_said <- function(levels, count, shown, minimum, coded) {
  if (coded || minimum <= 2 || !is.numeric(shown) || count %% (minimum - 1) != 0) return(NULL)
  if (levels == count || levels == count %/% (minimum - 1)) return(NULL)
  as.integer(levels)
}

# Whether a reader works out the rows of a folded level, as the Python `_folded_unsafe`.
mg_profile_folded_unsafe <- function(other, minimum, coded) {
  if (!coded) return(minimum <= 2)
  low <- max(0, other[1] - (coded - 1) * (minimum - 1))
  low == min(other[2], minimum - 1)
}

mg_profile_levels <- function(column, rows, minimum, dictionary) {
  text <- mg_text_of(column$present)
  levels <- unique(text)
  counted <- vapply(levels, function(level) sum(text == level), integer(1), USE.NAMES = FALSE)
  listed <- if (is.null(column$entry)) character() else mg_codes_of(column$entry, dictionary)
  listed <- unique(as.character(listed))
  rank <- match(levels, listed)
  rank[is.na(rank)] <- length(listed) + 1L
  order <- order(rank, levels, method = "radix")
  levels <- levels[order]
  counted <- counted[order]
  kept <- counted >= minimum
  folded <- !kept
  cells <- lapply(counted[kept], function(count) {
    mg_profile_cell(count, mg_profile_shown(count, minimum))
  })
  coded <- sum(!(listed %in% levels[kept]))
  if (any(folded)) {
    count <- sum(counted[folded])
    most <- if (coded) coded * (minimum - 1) else Inf
    cells <- c(cells, list(mg_profile_cell(count, mg_profile_shown(count, minimum), 1, most)))
  }
  cells <- c(cells, list(mg_profile_cell(column$missing,
                                         mg_profile_shown(column$missing, minimum))))
  cells <- mg_profile_beside(cells, minimum)
  # How many levels are folded is chosen once the count is printed or not, as in Python.
  said <- NULL
  if (any(folded)) {
    other_cell <- cells[[length(cells) - 1L]]
    said <- mg_profile_folded_said(sum(folded), other_cell$count, other_cell$shown, minimum,
                                   length(listed) > 0)
  }
  worked <- mg_profile_unsafe(cells, rows, minimum)
  if (any(folded) && !worked) {
    other <- mg_profile_ranges(cells, rows, minimum)[[length(cells) - 1L]]
    worked <- mg_profile_folded_unsafe(other, minimum, coded)
  }
  if (worked) return(mg_profile_held_view())
  out <- mg_profile_missing(column$missing, cells[[length(cells)]]$shown, rows, minimum)
  out$levels <- mg_arr(lapply(seq_len(sum(kept)), function(at) {
    mg_obj(level = levels[kept][at], count = mg_profile_json_count(cells[[at]]$shown))
  }))
  if (any(folded)) {
    out$other <- mg_obj(levels = mg_profile_json_count(said),
                        count = mg_profile_json_count(cells[[length(cells) - 1L]]$shown))
  }
  out
}

# A value's pattern: 9 for a digit, A and a for a letter in each case, ? for any other letter
# than ASCII's, every other character as it is.
mg_profile_shape_of <- function(text) {
  text <- enc2utf8(text)
  text <- gsub("[^\\x{00}-\\x{7f}]", "?", text, perl = TRUE)
  text <- gsub("[0-9]", "9", text, perl = TRUE)
  text <- gsub("[A-Z]", "A", text, perl = TRUE)
  gsub("[a-z]", "a", text, perl = TRUE)
}

# A column given nothing of its values, as the Python `_withheld`: its missing values, and the
# pattern its values share where that gives no count away.
mg_profile_withheld <- function(column, rows, minimum) {
  present <- length(column$present)
  shapes <- unique(mg_profile_shape_of(mg_text_of(column$present)))
  pattern <- if (present >= minimum && length(shapes) == 1) shapes else NULL
  missing <- mg_profile_cell(column$missing, mg_profile_shown(column$missing, minimum))
  tries <- if (is.null(pattern)) list(NULL) else list(pattern, NULL)
  for (given in tries) {
    rest <- mg_profile_cell(present, NULL, if (is.null(given)) 0 else minimum, hidden = TRUE)
    if (!mg_profile_unsafe(list(missing, rest), rows, minimum)) {
      out <- mg_profile_missing(column$missing, missing$shown, rows, minimum)
      if (!is.null(given)) out$pattern <- given
      return(out)
    }
  }
  mg_profile_held_view()
}

mg_profile_column <- function(column, rows, minimum, dictionary) {
  out <- list(name = column$name, type = column$kind,
              typed_by = if (is.null(column$entry)) "values" else "dictionary",
              kind = column$role)
  more <- switch(column$role,
    levels = mg_profile_levels(column, rows, minimum, dictionary),
    withheld = mg_profile_withheld(column, rows, minimum),
    mg_profile_distribution(column, rows, minimum)
  )
  if (!is.null(more$kind)) {
    out$kind <- more$kind
    more$kind <- NULL
  }
  if (!is.null(column$form) && out$kind == "date") out$format <- column$form
  structure(c(out, more), class = "mg_obj")
}

mg_profile_read_column <- function(name, values, entry, dates) {
  codes <- mg_missing_codes(entry)
  absent <- mg_absent(values, codes)
  present <- values[!absent]
  form <- dates[[name]]
  kind <- if (is.null(entry)) mg_profile_type_read(present, form) else entry$type
  role <- mg_profile_kind(entry, kind, mg_text_of(present))
  if (role != "date") form <- NULL
  list(name = name, entry = entry, kind = kind, role = role, form = form, present = present,
       missing = sum(absent))
}

# The profile of a table, as a document for `mg_profile_json`.
mg_profile <- function(data, name, minimum, dictionary = NULL, dataset = NULL, read_as = NULL) {
  if (is.null(minimum) || !is.numeric(minimum) || minimum < 1 || minimum != round(minimum)) {
    stop("profile: paper.yaml declares no `custodian: {minimum_cell_count: N}`, and every ",
         "count of the profile is held to it: write the custodian's, or 1 where there is no ",
         "rule", call. = FALSE)
  }
  minimum <- as.integer(minimum)
  mg_profile_check_name(name)
  read <- mg_profile_shape(name, read_as)
  if (!is.data.frame(data) && !(is.list(data) && !is.null(names(data)))) {
    stop("profile: give a data frame, or a named list of columns", call. = FALSE)
  }
  data <- as.list(data)
  if (anyDuplicated(names(data))) stop("profile: the table has two columns of one name",
                                       call. = FALSE)
  lengths <- unique(vapply(data, length, integer(1)))
  if (length(lengths) > 1) stop("profile: the columns given are not all of one length",
                                call. = FALSE)
  total <- if (length(lengths)) lengths else 0L
  entries <- list()
  if (!is.null(dictionary)) {
    listed <- vapply(dictionary$datasets, function(d) d$id, character(1))
    if (!is.null(dataset) && !(dataset %in% listed)) {
      stop("profile: the data dictionary lists no dataset ", dataset, call. = FALSE)
    }
    for (entry in dictionary$variables) {
      if (identical(entry$dataset, dataset)) entries[[entry$name]] <- entry
    }
  }
  unknown <- setdiff(names(read$dates), vapply(names(data), mg_profile_unmarked, character(1)))
  if (length(unknown)) {
    stop("profile: read_as dates names ", paste(sort(unknown, method = "radix"), collapse = ", "),
         ", which the table has no column of", call. = FALSE)
  }
  if (total < minimum) {
    stop("profile: the table has fewer rows than the data custodian's minimum of ", minimum,
         ", so every count of it would be below the minimum; no profile is written",
         call. = FALSE)
  }
  rows <- total
  columns_of <- names(data)
  if (length(columns_of) && startsWith(enc2utf8(columns_of[1]), mg_profile_mark)) {
    read$shape$bom <- TRUE
    read$shape$encoding <- "utf-8"
  }
  columns <- lapply(columns_of, function(name) {
    shown <- mg_profile_unmarked(name)
    column <- mg_profile_read_column(shown, data[[name]], entries[[shown]], read$dates)
    mg_profile_column(column, rows, minimum, dictionary)
  })
  mg_obj(schema = mg_profile_schema, name = name,
         dataset = if (is.null(dataset)) mg_null else dataset, minimum_cell_count = minimum,
         rows = as.integer(total),
         file = structure(read$shape, class = "mg_obj"), columns = mg_arr(columns))
}

mg_profile_unmarked <- function(name) {
  name <- enc2utf8(name)
  if (startsWith(name, mg_profile_mark)) substring(name, 2L) else name
}

# --------------------------------------------------------------------------- the JSON

# A text as Python's `json` writes it with its characters kept.
mg_profile_json_string <- function(text) {
  codes <- utf8ToInt(enc2utf8(text))
  out <- vapply(codes, function(code) {
    switch(as.character(code),
      "34" = "\\\"", "92" = "\\\\", "10" = "\\n", "13" = "\\r", "9" = "\\t", "8" = "\\b",
      "12" = "\\f",
      if (code < 32L) sprintf("\\u%04x", code) else intToUtf8(code)
    )
  }, character(1))
  paste0("\"", paste(out, collapse = ""), "\"")
}

mg_profile_json <- function(value, indent = 0L) {
  pad <- strrep(" ", indent)
  inner <- strrep(" ", indent + 2L)
  if (inherits(value, "mg_null")) return("null")
  if (inherits(value, "mg_fig")) return(unclass(value))
  if (inherits(value, "mg_obj")) {
    if (!length(value)) return("{}")
    items <- vapply(names(value), function(key) {
      paste0(inner, mg_profile_json_string(key), ": ", mg_profile_json(value[[key]], indent + 2L))
    }, character(1), USE.NAMES = FALSE)
    return(paste0("{\n", paste(items, collapse = ",\n"), "\n", pad, "}"))
  }
  if (inherits(value, "mg_arr")) {
    if (!length(value)) return("[]")
    items <- vapply(unclass(value), function(item) {
      paste0(inner, mg_profile_json(item, indent + 2L))
    }, character(1))
    return(paste0("[\n", paste(items, collapse = ",\n"), "\n", pad, "]"))
  }
  if (is.logical(value)) return(if (value) "true" else "false")
  if (is.numeric(value)) return(sprintf("%d", as.integer(value)))
  if (is.character(value)) return(mg_profile_json_string(value))
  stop("profile: cannot write a ", class(value)[1], call. = FALSE)
}

# Write the profile where `vault synthesize` reads it: profiles/data/<name>.profile.json.
mg_profile_write <- function(root, document) {
  path <- file.path(root, "profiles", "data", paste0(document$name, ".profile.json"))
  dir.create(dirname(path), recursive = TRUE, showWarnings = FALSE)
  json <- paste0(mg_profile_json(document), "\n")
  writeBin(charToRaw(enc2utf8(json)), path)
  invisible(path)
}
