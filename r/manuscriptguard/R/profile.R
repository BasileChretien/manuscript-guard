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

mg_profile_shown <- function(count, minimum) {
  held <- mg_held_back(count, minimum)
  if (is.null(held)) as.integer(count) else held
}

# The places of the counts held back that the total gives away, as the Python
# `custodian.recoverable_counts` reads a line: each count printed (an integer), held back
# behind the minimum ("<5", nought to four) or not printed (NULL, nought to the total).
mg_profile_recovered <- function(total, shown, minimum) {
  low <- vapply(shown, function(one) if (is.numeric(one)) as.numeric(one) else 0, numeric(1))
  high <- vapply(shown, function(one) {
    if (is.numeric(one)) as.numeric(one)
    else if (is.null(one)) as.numeric(total)
    else as.numeric(sub("^<", "", one)) - 1
  }, numeric(1))
  if (sum(low) > total || sum(high) < total) return(integer())
  found <- integer()
  for (at in seq_along(shown)) {
    if (is.numeric(shown[[at]])) next
    from <- max(low[at], total - (sum(high) - high[at]))
    to <- min(high[at], total - (sum(low) - low[at]))
    if (from == to && from >= 1 && from < minimum) found <- c(found, at)
  }
  found
}

# How each count of a column is printed: itself, "<m" below the minimum, or NULL where it is
# held back beside a count the total and the others would give away.
mg_profile_held_beside <- function(counts, total, minimum) {
  shown <- lapply(counts, mg_profile_shown, minimum = minimum)
  while (!is.null(total) && length(mg_profile_recovered(total, shown, minimum))) {
    exact <- which(vapply(shown, is.numeric, logical(1)))
    if (!length(exact)) break
    some <- exact[counts[exact] > 0]
    if (!length(some)) some <- exact
    shown[some[which.min(counts[some])]] <- list(NULL)
  }
  shown
}

mg_profile_json_count <- function(one) if (is.null(one)) mg_null else one

mg_profile_missing <- function(missing, shown, rows, minimum) {
  out <- list(missing = mg_profile_json_count(shown))
  if (is.numeric(shown) && missing >= minimum && missing > 0 && !is.null(rows) && rows > 0) {
    out$missing_share <- mg_fig(missing / rows)
  }
  out
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

mg_profile_centiles_of <- function(values, minimum, show) {
  ordered <- sort(values, method = "radix")
  n <- length(ordered)
  found <- list()
  if (!n) return(structure(found, class = "mg_obj"))
  for (centile in mg_profile_centiles) {
    value <- ordered[(centile * n + 99L) %/% 100L]
    below <- sum(ordered < value)
    above <- sum(ordered > value)
    if (below >= minimum && above >= minimum) found[[as.character(centile)]] <- show(value)
  }
  structure(found, class = "mg_obj")
}

mg_profile_month <- function(iso) {
  as.integer(substr(iso, 1, 4)) * 12L + as.integer(substr(iso, 6, 7)) - 1L
}

mg_profile_month_shown <- function(month) sprintf("%04d-%02d", month %/% 12L, month %% 12L + 1L)

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
  shown <- mg_profile_held_beside(c(column$missing, sum(!ok), sum(ok)), rows, minimum)
  out <- mg_profile_missing(column$missing, shown[[1]], rows, minimum)
  out$unread <- mg_profile_json_count(shown[[2]])
  out$n <- mg_profile_json_count(shown[[3]])
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
  out
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
  counts <- counted[kept]
  folded <- !kept
  if (any(folded)) counts <- c(counts, sum(counted[folded]))
  shown <- mg_profile_held_beside(c(counts, column$missing), rows, minimum)
  out <- mg_profile_missing(column$missing, shown[[length(shown)]], rows, minimum)
  out$levels <- mg_arr(lapply(seq_len(sum(kept)), function(at) {
    mg_obj(level = levels[kept][at], count = mg_profile_json_count(shown[[at]]))
  }))
  if (any(folded)) {
    out$other <- mg_obj(levels = sum(folded),
                        count = mg_profile_json_count(shown[[length(shown) - 1L]]))
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

mg_profile_withheld <- function(column, rows, minimum) {
  out <- mg_profile_missing(column$missing, mg_profile_shown(column$missing, minimum), rows,
                            minimum)
  shapes <- unique(mg_profile_shape_of(mg_text_of(column$present)))
  if (length(column$present) >= minimum && length(shapes) == 1) out$pattern <- shapes
  out
}

mg_profile_column <- function(column, rows, minimum, dictionary) {
  out <- list(name = column$name, type = column$kind,
              typed_by = if (is.null(column$entry)) "values" else "dictionary",
              kind = column$role)
  if (!is.null(column$form) && column$role == "date") out$format <- column$form
  more <- switch(column$role,
    levels = mg_profile_levels(column, rows, minimum, dictionary),
    withheld = mg_profile_withheld(column, rows, minimum),
    mg_profile_distribution(column, rows, minimum)
  )
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
  unknown <- setdiff(names(read$dates), names(data))
  if (length(unknown)) {
    stop("profile: read_as dates names ", paste(sort(unknown, method = "radix"), collapse = ", "),
         ", which the table has no column of", call. = FALSE)
  }
  held <- mg_held_back(total, minimum)
  rows <- if (is.null(held)) total else NULL
  columns <- lapply(names(data), function(name) {
    column <- mg_profile_read_column(name, data[[name]], entries[[name]], read$dates)
    mg_profile_column(column, rows, minimum, dictionary)
  })
  mg_obj(schema = mg_profile_schema, name = name, minimum_cell_count = minimum,
         rows = if (is.null(held)) as.integer(total) else held,
         file = structure(read$shape, class = "mg_obj"), columns = mg_arr(columns))
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
