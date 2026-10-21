# What the data hold, against what the data dictionary says they should hold: the Python
# `quality` module, check for check. What a value is read as (missing, a number, a date, a
# code as text) is written down there once, and tests/data/quality holds both emitters to
# the same counts. Counts only: no value of any row leaves the script.

mg_quality_checks <- c("missing", "wrong_type", "out_of_range", "not_allowed",
                       "not_matching", "outside_period", "not_applicable")
mg_quality_coded <- c("binary", "categorical", "ordinal")
mg_quality_numeric <- c("continuous", "count")
mg_quality_temporal <- c("date", "datetime", "time")
mg_quality_reserved <- c("rows", "rule")
mg_quality_space <- "[ \t\r\n]"
mg_quality_decimal <- "^[+-]?(?:[0-9]+(?:[.][0-9]*)?|[.][0-9]+)(?:[eE][+-]?[0-9]+)?$"
mg_quality_date <- "^([0-9]{4})-([0-9]{2})-([0-9]{2})$"
mg_quality_datetime <- paste0(
  "^([0-9]{4})-([0-9]{2})-([0-9]{2})[T ]([0-9]{2}):([0-9]{2})",
  "(?::([0-9]{2})(?:[.][0-9]+)?)?(?:Z|[+-][0-9]{2}:?[0-9]{2})?$"
)
mg_quality_time <- "^([0-9]{2}):([0-9]{2})(?::([0-9]{2}))?$"

# A variable's name as a result key holds it: in lower case, a dot an underscore.
mg_slug <- function(name) gsub("[^a-z0-9_]", "_", tolower(name))

mg_trim <- function(x) trimws(x, whitespace = mg_quality_space)

# The time zone a date and time is shown in: its own, or the session's where it has none, as
# the clock it was written with reads.
mg_tz <- function(x) {
  tz <- attr(x, "tzone")
  if (is.null(tz) || !nzchar(tz[1])) "" else tz[1]
}

# Values as text, as the Python `text_of`: a truth value "true" or "false", a whole number its
# digits, any other number to fifteen significant digits, a date in ISO 8601.
mg_text_of <- function(x) {
  if (is.factor(x)) x <- as.character(x)
  if (inherits(x, "Date")) return(format(x, "%Y-%m-%d"))
  if (inherits(x, "POSIXt")) return(format(x, "%Y-%m-%dT%H:%M:%S", tz = mg_tz(x)))
  if (is.logical(x)) return(ifelse(is.na(x), NA_character_, ifelse(x, "true", "false")))
  if (inherits(x, "integer64")) return(as.character(x))
  if (is.numeric(x)) {
    x <- as.numeric(x)
    out <- rep(NA_character_, length(x))
    finite <- is.finite(x)
    # Below 2^53 a double holds every whole number; above it sprintf on Windows prints
    # digits the double does not hold, so it is written as any other number.
    whole <- finite & x == round(x) & abs(x) < 2^53
    out[whole] <- sprintf("%.0f", x[whole])
    out[whole & x == 0] <- "0"
    out[finite & !whole] <- sprintf("%.15g", x[finite & !whole])
    out[!is.na(x) & x == Inf] <- "inf"
    out[!is.na(x) & x == -Inf] <- "-inf"
    return(out)
  }
  as.character(x)
}

# Whether each value is missing: NA, a blank text, or one of the variable's missing codes.
mg_absent <- function(x, codes = character()) {
  text <- mg_text_of(x)
  out <- is.na(x) | is.na(text)
  out <- out | (!is.na(text) & !nzchar(mg_trim(text)) & (is.character(x) | is.factor(x)))
  if (length(codes) > 0) out <- out | (!is.na(text) & text %in% codes)
  out
}

# Values as finite numbers, NA where one is not: a number, or a text in decimal notation.
mg_number_of <- function(x) {
  if (is.factor(x)) x <- as.character(x)
  if (is.logical(x) || inherits(x, c("Date", "POSIXt"))) return(rep(NA_real_, length(x)))
  if (is.numeric(x)) {
    out <- as.numeric(x)
  } else if (is.character(x)) {
    trimmed <- mg_trim(x)
    ok <- !is.na(trimmed) & grepl(mg_quality_decimal, trimmed, perl = TRUE)
    out <- rep(NA_real_, length(x))
    out[ok] <- as.numeric(trimmed[ok])
  } else {
    return(rep(NA_real_, length(x)))
  }
  out[!is.finite(out)] <- NA_real_
  out
}

# "YYYY-MM-DD" where the parts are a day of the calendar, from year 1; NA where they are not.
mg_calendar <- function(year, month, day) {
  candidate <- sprintf("%s-%s-%s", year, month, day)
  parsed <- as.Date(candidate, format = "%Y-%m-%d")
  ok <- as.integer(year) >= 1 & !is.na(parsed) &
    format(parsed, "%Y-%m-%d") == candidate
  ifelse(!is.na(ok) & ok, candidate, NA_character_)
}

mg_clock <- function(hour, minute, second) {
  second[!nzchar(second)] <- "00"
  ok <- as.integer(hour) <= 23 & as.integer(minute) <= 59 & as.integer(second) <= 59
  ifelse(!is.na(ok) & ok, paste(hour, minute, second, sep = ":"), NA_character_)
}

# The parts a pattern's groups matched, one row for each value; NA where it did not match.
mg_parts <- function(x, pattern, groups) {
  out <- matrix(NA_character_, nrow = length(x), ncol = groups)
  if (!length(x)) return(out)
  trimmed <- mg_trim(x)
  ok <- !is.na(trimmed) & grepl(pattern, trimmed, perl = TRUE)
  if (any(ok)) {
    found <- regmatches(trimmed[ok], regexec(pattern, trimmed[ok], perl = TRUE))
    out[ok, ] <- t(vapply(found, function(m) m[2:(groups + 1L)], character(groups)))
  }
  out
}

mg_date_of <- function(x) {
  if (inherits(x, "Date")) return(format(x, "%Y-%m-%d"))
  if (inherits(x, "POSIXt")) return(format(x, "%Y-%m-%d", tz = mg_tz(x)))
  if (is.factor(x)) x <- as.character(x)
  if (!is.character(x)) return(rep(NA_character_, length(x)))
  parts <- mg_parts(x, mg_quality_date, 3L)
  mg_calendar(parts[, 1], parts[, 2], parts[, 3])
}

mg_datetime_of <- function(x) {
  if (inherits(x, "POSIXt")) return(format(x, "%Y-%m-%dT%H:%M:%S", tz = mg_tz(x)))
  if (inherits(x, "Date")) {
    return(ifelse(is.na(x), NA_character_, paste0(format(x, "%Y-%m-%d"), "T00:00:00")))
  }
  if (is.factor(x)) x <- as.character(x)
  if (!is.character(x)) return(rep(NA_character_, length(x)))
  parts <- mg_parts(x, mg_quality_datetime, 6L)
  day <- mg_calendar(parts[, 1], parts[, 2], parts[, 3])
  clock <- mg_clock(parts[, 4], parts[, 5], parts[, 6])
  ifelse(is.na(day) | is.na(clock), NA_character_, paste0(day, "T", clock))
}

mg_time_of <- function(x) {
  if (is.factor(x) || inherits(x, "hms")) x <- as.character(x)
  if (!is.character(x)) return(rep(NA_character_, length(x)))
  parts <- mg_parts(x, mg_quality_time, 3L)
  mg_clock(parts[, 1], parts[, 2], parts[, 3])
}

mg_read_as <- function(kind) {
  switch(kind, date = mg_date_of, datetime = mg_datetime_of, time = mg_time_of)
}

# An ISO date, date and time or time as a number that sorts as it does, so that comparing
# two never depends on the locale's collation.
mg_sortable <- function(text) suppressWarnings(as.numeric(gsub("[^0-9]", "", text)))

mg_text_codes <- function(listed) {
  vapply(listed, function(coded) mg_text_of(coded$code), character(1))
}

mg_codes_of <- function(entry, dictionary) {
  listed <- entry$values
  if (is.null(listed) && !is.null(entry$code_list)) {
    listed <- dictionary$code_lists[[entry$code_list]]
    if (is.null(listed)) {
      stop("data dictionary: ", entry$name, " names code list ", entry$code_list,
           ", which code_lists does not hold", call. = FALSE)
    }
  }
  if (is.null(listed)) NULL else mg_text_codes(listed)
}

mg_missing_codes <- function(entry) {
  if (is.null(entry$missing)) character() else mg_text_codes(entry$missing)
}

mg_checks_of <- function(entry, dictionary) {
  kind <- entry$type
  asked <- "missing"
  if (kind %in% c(mg_quality_numeric, mg_quality_temporal)) asked <- c(asked, "wrong_type")
  if (!is.null(entry$range) && kind %in% c(mg_quality_numeric, mg_quality_temporal)) {
    asked <- c(asked, "out_of_range")
  }
  if (kind %in% mg_quality_coded && !is.null(mg_codes_of(entry, dictionary))) {
    asked <- c(asked, "not_allowed")
  }
  if (!is.null(entry$pattern) && nzchar(entry$pattern)) asked <- c(asked, "not_matching")
  if (isTRUE(entry$within_study_period) && !is.null(dictionary$study_period) &&
      kind %in% c("date", "datetime")) {
    asked <- c(asked, "outside_period")
  }
  if (!is.null(entry$applies_if)) asked <- c(asked, "not_applicable")
  mg_quality_checks[mg_quality_checks %in% asked]
}

# A range bound, read as the variable's values are; refused where it cannot be.
mg_bound <- function(entry, which) {
  given <- entry$range[[which]]
  if (is.null(given)) return(NULL)
  kind <- entry$type
  read <- if (kind %in% mg_quality_numeric) {
    mg_number_of(given)
  } else if (kind %in% mg_quality_temporal) {
    mg_sortable(mg_read_as(kind)(as.character(given)))
  } else {
    NA
  }
  if (is.na(read)) {
    stop("data dictionary: ", entry$name, "'s range ", which, " ", given, " is not a ", kind,
         " value", call. = FALSE)
  }
  read
}

# For each row, whether the variable applies: TRUE, FALSE, or NA where the variable it
# depends on holds no value.
mg_applies <- function(entry, data, entries) {
  condition <- entry$applies_if
  if (is.null(condition)) return(NULL)
  other <- condition$variable
  if (!(other %in% names(data))) {
    stop("check_data: ", entry$name, " applies only where ", other, " holds one of its ",
         "codes, and the table has no column ", other, call. = FALSE)
  }
  values <- data[[other]]
  unknown <- if (is.null(entries[[other]])) character() else mg_missing_codes(entries[[other]])
  codes <- vapply(condition[["in"]], mg_text_of, character(1))
  ifelse(mg_absent(values, unknown), NA, mg_text_of(values) %in% codes)
}

# The rows each of a variable's checks counts, as one truth value for each row.
mg_check_variable <- function(entry, values, dictionary, applies = NULL) {
  kind <- entry$type
  checks <- mg_checks_of(entry, dictionary)
  rows <- length(values)
  found <- lapply(stats::setNames(checks, checks), function(check) logical(rows))
  here <- if (is.null(applies)) rep(TRUE, rows) else applies
  missing <- mg_absent(values, mg_missing_codes(entry))
  present <- !missing
  found$missing <- missing & !is.na(here) & here
  if ("not_applicable" %in% checks) found$not_applicable <- present & !is.na(here) & !here
  text <- mg_text_of(values)
  if ("not_matching" %in% checks) {
    pattern <- paste0("^(?:", entry$pattern, ")\\z")
    found$not_matching <- present & !grepl(pattern, text, perl = TRUE)
  }
  if (kind %in% mg_quality_coded) {
    if ("not_allowed" %in% checks) {
      found$not_allowed <- present & !(text %in% mg_codes_of(entry, dictionary))
    }
    return(found)
  }
  if (kind %in% mg_quality_numeric) {
    read <- mg_number_of(values)
    wrong <- is.na(read) | (kind == "count" & !is.na(read) & (read < 0 | read != round(read)))
  } else if (kind %in% mg_quality_temporal) {
    iso <- mg_read_as(kind)(values)
    read <- mg_sortable(iso)
    wrong <- is.na(read)
    if ("outside_period" %in% checks) {
      period <- dictionary$study_period
      day <- mg_sortable(substr(iso, 1, 10))
      outside <- day < mg_sortable(period$start) | day > mg_sortable(period$end)
      found$outside_period <- present & !wrong & outside
    }
  } else {
    return(found)
  }
  found$wrong_type <- present & wrong
  if ("out_of_range" %in% checks) {
    low <- mg_bound(entry, "min")
    high <- mg_bound(entry, "max")
    out <- rep(FALSE, rows)
    if (!is.null(low)) out <- out | (!is.na(read) & read < low)
    if (!is.null(high)) out <- out | (!is.na(read) & read > high)
    found$out_of_range <- present & !wrong & out
  }
  found
}

# What an order rule compares its variables as; a rule over two families is refused.
mg_family <- function(entries) {
  kinds <- unique(vapply(entries, function(entry) entry$type, character(1)))
  if (all(kinds %in% mg_quality_numeric)) return("number")
  if (all(kinds %in% c("date", "datetime"))) return(if ("date" %in% kinds) "date" else "datetime")
  if (identical(kinds, "time")) return("time")
  stop("data dictionary: an order rule compares numbers, dates or times, one of them; not ",
       paste(sort(kinds), collapse = ", "), call. = FALSE)
}

mg_comparable <- function(entry, family, values) {
  if (family == "number") return(mg_number_of(values))
  iso <- mg_read_as(entry$type)(values)
  if (family == "date") iso <- substr(iso, 1, 10)
  mg_sortable(iso)
}

# The rows where each value is present and of its type, and one is greater than the next.
mg_check_order <- function(entries, columns) {
  family <- mg_family(entries)
  rows <- length(columns[[1]])
  usable <- rep(TRUE, rows)
  read <- vector("list", length(entries))
  for (i in seq_along(entries)) {
    usable <- usable & !mg_absent(columns[[i]], mg_missing_codes(entries[[i]]))
    read[[i]] <- mg_comparable(entries[[i]], family, columns[[i]])
    usable <- usable & !is.na(read[[i]])
  }
  broken <- rep(FALSE, rows)
  for (i in seq_len(length(entries) - 1L)) {
    broken <- broken | (usable & read[[i]] > read[[i + 1L]])
  }
  broken & usable
}

mg_key_text <- function(entry, values) {
  kind <- entry$type
  if (kind %in% mg_quality_numeric) {
    read <- mg_number_of(values)
    return(ifelse(is.na(read), mg_text_of(values), mg_text_of(read)))
  }
  if (kind %in% mg_quality_temporal) {
    read <- mg_read_as(kind)(values)
    return(ifelse(is.na(read), mg_text_of(values), read))
  }
  mg_text_of(values)
}

# The rows whose values of the key are those of a row before them. A row with a part of
# its key missing is no duplicate: it is counted as missing.
mg_check_unique <- function(entries, columns) {
  rows <- length(columns[[1]])
  usable <- rep(TRUE, rows)
  parts <- vector("list", length(entries))
  for (i in seq_along(entries)) {
    usable <- usable & !mg_absent(columns[[i]], mg_missing_codes(entries[[i]]))
    text <- mg_key_text(entries[[i]], columns[[i]])
    # Each part prefixed by its length, so that no two keys join into one text.
    parts[[i]] <- paste0(nchar(text, type = "chars"), ":", text)
  }
  key <- do.call(paste, c(parts, sep = "|"))
  repeated <- rep(FALSE, rows)
  repeated[usable] <- duplicated(key[usable])
  repeated
}

mg_refuse_clashes <- function(dictionary) {
  seen <- character()
  for (entry in dictionary$variables) {
    key <- mg_slug(entry$name)
    if (key %in% mg_quality_reserved) {
      stop("data dictionary: a variable named ", entry$name, " would put its counts beside ",
           "quality.", key, "; rename it", call. = FALSE)
    }
    if (key %in% names(seen)) {
      stop("data dictionary: ", seen[[key]], " and ", entry$name, " would both be counted ",
           "under quality.", key, "; rename one", call. = FALSE)
    }
    seen[[key]] <- entry$name
  }
  invisible(NULL)
}

mg_read_dictionary <- function(path) {
  if (!requireNamespace("yaml", quietly = TRUE)) {
    stop("check_data reads the data dictionary with the yaml package: ",
         "install.packages(\"yaml\")", call. = FALSE)
  }
  if (!file.exists(path)) {
    stop("check_data: no data dictionary at ", path, "; write one first (the analysis-plan ",
         "skill has the outline)", call. = FALSE)
  }
  dictionary <- yaml::read_yaml(path, fileEncoding = "UTF-8")
  if (!identical(dictionary$schema, "manuscript-guard/data-dictionary/1") ||
      !is.list(dictionary$variables)) {
    stop("check_data: ", basename(path), " is not a data dictionary: it names the schema ",
         "manuscript-guard/data-dictionary/1 and lists its variables", call. = FALSE)
  }
  for (entry in dictionary$variables) {
    if (is.null(entry$name) || is.null(entry$type)) {
      stop("check_data: ", basename(path), ": each variable has a name and a type",
           call. = FALSE)
    }
  }
  dictionary
}

mg_minimum_cell_count <- function(root) {
  path <- file.path(root, "paper.yaml")
  if (!file.exists(path) || !requireNamespace("yaml", quietly = TRUE)) return(NULL)
  paper <- tryCatch(yaml::read_yaml(path, fileEncoding = "UTF-8"), error = function(e) NULL)
  minimum <- paper$custodian$minimum_cell_count
  if (is.numeric(minimum) && length(minimum) == 1 && !is.na(minimum) &&
      minimum == round(minimum)) as.integer(minimum) else NULL
}

mg_held_back <- function(count, minimum) {
  if (!is.null(minimum) && count > 0 && count < minimum) paste0("<", minimum) else NULL
}

# A computed rule's rows, as the script found them: one truth value for each row.
mg_computed <- function(rule_id, flags, rules, rows) {
  rule <- rules[[rule_id]]
  if (is.null(rule)) stop("check_data: the data dictionary has no rule ", rule_id, call. = FALSE)
  if (!isTRUE(rule$computed)) {
    stop("check_data: rule ", rule_id, " is not `computed: true`; check_data finds the rows ",
         "of an order or a unique rule itself", call. = FALSE)
  }
  if (length(flags) != rows) {
    stop("check_data: rule ", rule_id, " was given ", length(flags), " truth values for a ",
         "table of ", rows, " rows; give one for each row, TRUE where the row breaks the ",
         "rule", call. = FALSE)
  }
  if (!is.logical(flags) || anyNA(flags)) {
    stop("check_data: rule ", rule_id, " was given something other than TRUE or FALSE for ",
         "a row; say for every row whether it breaks the rule", call. = FALSE)
  }
  as.vector(flags)
}

# Every count a check of one table finds, as a named list of truth values for each row,
# keyed as the results hold them after `quality.`.
mg_check_table <- function(dictionary, data, dataset = NULL, computed = NULL) {
  mg_refuse_clashes(dictionary)
  if (!is.data.frame(data) && !(is.list(data) && !is.null(names(data)))) {
    stop("check_data: give a data frame, or a named list of columns", call. = FALSE)
  }
  data <- as.list(data)
  if (anyDuplicated(names(data))) stop("check_data: the table has two columns of one name",
                                       call. = FALSE)
  lengths <- unique(vapply(data, length, integer(1)))
  if (length(lengths) > 1) {
    stop("check_data: the columns given are not all of one length", call. = FALSE)
  }
  rows <- if (length(lengths)) lengths else 0L
  listed <- vapply(dictionary$datasets, function(d) d$id, character(1))
  if (!is.null(dataset) && !(dataset %in% listed)) {
    stop("check_data: the data dictionary lists no dataset ", dataset, "; ",
         if (length(listed)) paste("it lists", paste(listed, collapse = ", ")) else "it lists none",
         call. = FALSE)
  }
  entries <- Filter(function(entry) identical(entry$dataset, dataset), dictionary$variables)
  by_name <- stats::setNames(dictionary$variables,
                             vapply(dictionary$variables, function(e) e$name, character(1)))
  present <- Filter(function(entry) entry$name %in% names(data), entries)
  if (!length(present) && !length(computed)) {
    named <- vapply(utils::head(entries, 5), function(e) e$name, character(1))
    stop("check_data: the table has no column the data dictionary lists",
         if (is.null(dataset)) "" else paste0(" of dataset ", dataset),
         " (it lists ", if (length(named)) paste(named, collapse = ", ") else "none", ")",
         call. = FALSE)
  }
  found <- list()
  for (entry in present) {
    applies <- mg_applies(entry, data, by_name)
    checked <- mg_check_variable(entry, data[[entry$name]], dictionary, applies)
    names(checked) <- paste0(mg_slug(entry$name), ".", names(checked))
    found <- c(found, checked)
  }
  here <- vapply(present, function(entry) entry$name, character(1))
  rules <- if (is.null(dictionary$rules)) list() else dictionary$rules
  names(rules) <- vapply(rules, function(rule) rule$id, character(1))
  for (rule in rules) {
    ruled <- if (!is.null(rule$order)) unlist(rule$order) else unlist(rule$unique)
    if (is.null(ruled) || !all(ruled %in% here)) next
    columns <- lapply(ruled, function(name) data[[name]])
    flags <- if (!is.null(rule$order)) {
      mg_check_order(by_name[ruled], columns)
    } else {
      mg_check_unique(by_name[ruled], columns)
    }
    found[[paste0("rule.", rule$id)]] <- flags
  }
  for (rule_id in names(computed)) {
    found[[paste0("rule.", rule_id)]] <- mg_computed(rule_id, computed[[rule_id]], rules, rows)
  }
  list(rows = rows, found = found)
}
