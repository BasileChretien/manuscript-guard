#' Find the project root
#'
#' Walks upwards looking for paper.yaml, the way git looks for .git.
#'
#' @param start Directory to start from. Defaults to the working directory.
#' @return Absolute path to the project root.
#' @export
mg_find_root <- function(start = getwd()) {
  current <- normalizePath(start, winslash = "/", mustWork = TRUE)
  repeat {
    if (file.exists(file.path(current, "paper.yaml"))) {
      return(current)
    }
    parent <- dirname(current)
    if (identical(parent, current)) {
      stop("no paper.yaml found in ", start, " or any parent directory", call. = FALSE)
    }
    current <- parent
  }
}

#' Check that an explicit display is a rendering of its own value
#'
#' Mirrors `_check_display_matches` in the Python emitter, and must keep mirroring it: the
#' results fragment is a cross-language contract, and a rule enforced on one side only is a
#' rule an author can step around by switching language.
#'
#' Nothing used to compare the two, so one call could publish a fabricated estimate and a
#' fabricated interval at once. Only numbers are checked; a string value is its own display,
#' and a label such as "2015-2024" is a value rather than a rounding of one.
#' @noRd
mg_check_display <- function(key, value, display) {
  if (is.logical(value) || !is.numeric(value)) {
    return(invisible(NULL))
  }
  # digits, optional decimals, optional exponent, optional unit carrying no digits of its
  # own. Without that last condition "(95% CI 2.10 to 7.02)" parses as the unit of 3.84.
  # The leading comparator is not decoration. "<0.001" is how a p-value too small to state
  # is written, and R rejected it while Python accepted it - so an analysis emitting a
  # rounded p-value was legal in one language and an error in the other, which is exactly
  # the divergence the docstring above warns about. Found by a cross-language test rather
  # than by reading: both emitters have to be exercised on the same input, or "mirrors" is
  # only a claim.
  # The exponent has two spellings, and the second is the one a paper is written in:
  # 3.2e-9 as a programmer types it, "3.2 x 10^-9" with superscripts as a journal prints it.
  # Without it a p-value worth stating precisely could be written only in a notation no
  # journal uses, and the alternative an author reaches for is `digits`, which rounds it away.
  pattern <- paste0(
    "^\\s*(<=|>=|<|>|\u2264|\u2265)?\\s*([-+\u2212]?)",
    "((?:\\d{1,3}(?:[,\u00a0\u202f ]\\d{3})+(?:\\.\\d+)?)|(?:\\d+(?:\\.\\d+)?))",
    "(?:[eE]([-+]?\\d+)",
    "|\\s*[x\u00d7*]\\s*10\\s*(?:\\^|\\*\\*)?\\s*",
    "([-+\u2212]?[0-9]+|[\u207b\u207a]?[\u2070\u00b9\u00b2\u00b3\u2074\u2075\u2076\u2077\u2078\u2079]+))?",
    "\\s*(%|[^\\s\\d][^\\d]*?)?\\s*$"
  )
  parts <- regmatches(display, regexec(pattern, display, perl = TRUE))[[1]]
  if (length(parts) == 0) {
    stop(
      key, ": display '", display, "' is not a rendering of ", format(value),
      ". A display carries one number, optionally with a unit - an interval or a sentence ",
      "belongs in separate keys, so each part can be quoted and checked on its own",
      call. = FALSE
    )
  }

  text <- gsub("[,\u00a0\u202f ]", "", parts[4])
  if (identical(parts[3], "-") || identical(parts[3], "\u2212")) {
    text <- paste0("-", text)
  }
  exponent <- mg_exponent(parts[5], parts[6])
  if (nzchar(exponent)) {
    text <- paste0(text, "e", exponent)
  }

  shown <- as.numeric(text)

  if (nzchar(parts[2])) {
    # "<0.001" is true of any value below 0.001 and false of 0.4. Checking the direction
    # rather than the distance is the whole content of a comparator display.
    below <- parts[2] %in% c("<", "<=", "\u2264")
    satisfied <- if (below) value <= shown else value >= shown
    if (!satisfied) {
      stop(
        key, ": display '", display, "' says the value is ",
        if (below) "below " else "above ", format(shown), ", but it is ", format(value),
        call. = FALSE
      )
    }
    return(invisible(NULL))
  }

  decimals <- if (grepl("\\.", text)) nchar(sub("^[^.]*\\.", "", sub("e.*$", "", text))) else 0
  # Half a unit in the last place *shown*, and "shown" has to account for the exponent. The
  # Python side learned this and R did not: from the mantissa alone the tolerance is a fixed
  # ~0.005 however small the number is, so below about 1e-3 the check stopped meaning
  # anything - R accepted a display of "9.99e-6" for a value of 1.2e-6 while Python refused
  # it. The parity test never noticed, because none of its cases carried an exponent.
  power <- if (nzchar(exponent)) as.integer(exponent) else 0L
  tolerance <- 0.5 * (10^(power - decimals)) + abs(value) * 1e-9
  if (abs(shown - value) > tolerance) {
    stop(
      key, ": display '", display, "' reads as ", format(shown), ", but the value is ",
      format(value), ". Round it with `digits` rather than writing the number twice; if the ",
      "display is in different units, emit the value in those units and name them with `unit`",
      call. = FALSE
    )
  }
  invisible(NULL)
}

#' Display string for a value
#'
#' Mirrors the Python emitter exactly, with one concession to R: a double holding a whole
#' number is treated as a count, because R has no integer literal that survives ordinary
#' arithmetic. A quantity that really is 3.0 and should read "3.00" therefore needs an
#' explicit `digits`.
#' @noRd
mg_display <- function(key, value, display, digits) {
  if (!is.null(display)) {
    display <- as.character(display)
    mg_check_display(key, value, display)
    return(display)
  }
  if (is.logical(value)) {
    return(if (isTRUE(value)) "TRUE" else "FALSE")
  }
  if (is.character(value)) {
    return(value)
  }
  if (is.numeric(value)) {
    if (!is.null(digits)) {
      shown <- sprintf(paste0("%.", as.integer(digits), "f"), value)
      # A rounding that turns a real number into zero is not a rounding of it. A p-value of
      # 3.2e-9 with digits = 2 was published as "0.00": the emitter printing a number that is
      # not the number, silently. An explicit display is checked against its value; a derived
      # one was checked against nothing.
      if (value != 0 && as.numeric(shown) == 0) {
        stop(
          key, ": rounding ", format(value), " to ", as.integer(digits),
          " decimal place(s) gives '", shown, "', which is not this number. Say what the ",
          "paper should print: display = '<0.001' for a value too small to state, or ",
          "display = '3.2 x 10^-9' for one worth stating precisely - both are checked ",
          "against the value",
          call. = FALSE
        )
      }
      return(shown)
    }
    if (is.integer(value) || (is.finite(value) && value == round(value) && abs(value) < 1e15)) {
      return(format(value, scientific = FALSE, trim = TRUE))
    }
    stop(
      key, ": a non-integer number needs `display` or `digits` so that every place it is ",
      "quoted rounds it identically",
      call. = FALSE
    )
  }
  stop(key, ": values of this type need an explicit `display`", call. = FALSE)
}

#' Write text with LF endings on every platform
#'
#' `writeLines(x, path)` opens a *text* connection, and on Windows a text connection
#' translates every newline to CRLF. `useBytes = TRUE` does not prevent it — that argument
#' is about encoding, not line endings. So the same analysis run on Windows and on Linux
#' produced byte-different results fragments, and since the guarantee here is a byte digest
#' over the file, a fragment written on one and checked out on the other reported
#' `results-edited` for a file nobody had touched. A binary connection writes what it is
#' given. This matches `newline="\n"` on every writer in the Python package.
#' @noRd
mg_write_lf <- function(text, path) {
  con <- file(path, open = "wb")
  on.exit(close(con), add = TRUE)
  writeLines(text, con, sep = "\n", useBytes = TRUE)
  invisible(path)
}

#' Suffixes an analysis script can have, where a line ending is formatting not substance
#' @noRd
MG_SOURCE_SUFFIXES <- c("py", "r", "rmd", "qmd", "jl", "do", "sas", "sh")

#' Suffixes of DATA an analysis reads, with the same property
#'
#' Mirrors `_DATA_SUFFIXES` in the Python emitter and must stay identical to it. Without this,
#' the digest chain did not survive a git checkout: a project writing CSVs on Windows records
#' CRLF digests, .gitattributes normalises the blob to LF, and a fresh clone then mismatches
#' every declared input on every platform. Anything absent from this list is hashed byte for
#' byte, which is the right default wherever a CR is content.
#' @noRd
MG_DATA_SUFFIXES <- c("csv", "tsv", "psv", "json", "jsonl", "yaml", "yml", "toml",
                      "md", "bib", "xml")

#' The digest of a script, ignoring line endings
#'
#' Mirrors `source_digest` in the Python emitter, and must stay identical to it: an R-written
#' fragment and a Python-written one have to describe the same file the same way. Distinct
#' from the fragment digest, which stays byte-exact on purpose — see `mg_write_lf` above for
#' the sibling problem. Git rewrites line endings on checkout, and CRLF instead of LF cannot
#' change what a script computed; hashing the raw bytes made G1 report `script-newer` for a
#' script nobody had touched.
#' @noRd
mg_digest_in <- function(path, suffixes) {
  suffix <- tolower(tools::file_ext(path))
  raw_bytes <- readBin(path, "raw", file.info(path)$size)

  # UTF-16 is never normalised: 0x0D and 0x0A occur as bytes of ordinary characters there,
  # so rewriting them corrupts text rather than reformatting it. Matches `_is_utf16` on the
  # Python side.
  is_utf16 <- length(raw_bytes) >= 2 &&
    (identical(raw_bytes[1:2], as.raw(c(0xff, 0xfe))) ||
     identical(raw_bytes[1:2], as.raw(c(0xfe, 0xff))))
  if (!(suffix %in% suffixes) || is_utf16) {
    return(digest::digest(file = path, algo = "sha256"))
  }

  # Operated on RAW vectors, not on a string. The previous version called rawToChar first,
  # which R refuses for any file containing an embedded NUL - so an analysis declaring a
  # UTF-16 or NUL-bearing input died inside the emitter with an opaque error, on files that
  # digest::digest(file=) had handled before this function existed. Python returns a digest
  # for those, so the crash was also a parity break.
  #
  # Drop CR before LF, then any surviving lone CR - the same two steps, in the same order, as
  # the Python side. Order matters: dropping every CR first would turn a lone CR into nothing
  # rather than into a newline.
  cr <- as.raw(0x0d)
  lf <- as.raw(0x0a)
  n <- length(raw_bytes)
  if (n > 0L) {
    is_cr <- raw_bytes == cr
    follows_lf <- c(raw_bytes[-1L] == lf, FALSE)
    raw_bytes <- raw_bytes[!(is_cr & follows_lf)]   # CRLF -> LF
    raw_bytes[raw_bytes == cr] <- lf                # lone CR -> LF
  }
  digest::digest(raw_bytes, algo = "sha256", serialize = FALSE)
}

mg_source_digest <- function(path) {
  mg_digest_in(path, MG_SOURCE_SUFFIXES)
}

#' The digest of a lockfile, ignoring line endings whatever its suffix
#'
#' Mirrors `lockfile_digest` in the Python emitter: renv.lock, uv.lock and a requirements file
#' can hold no line end inside a value, and `.lock` and `.txt` name other things too.
#' @noRd
mg_lockfile_digest <- function(path) {
  mg_digest_in(path, tolower(tools::file_ext(path)))
}

#' The digest of a file the analysis READ, ignoring line endings where they are formatting
#'
#' Mirrors `input_digest` in the Python emitter and must stay identical to it. Distinct from
#' the fragment's own digest, which stays byte-exact because it has to be reproducible from
#' any language that can emit results. Nobody reproduces an input; they check it has not
#' changed, and a line ending git rewrote on checkout is not a change.
#' @noRd
mg_input_digest <- function(path) {
  mg_digest_in(path, c(MG_SOURCE_SUFFIXES, MG_DATA_SUFFIXES))
}

#' The exponent a display carries, whichever of its two spellings was used
#'
#' Mirrors `_exponent_of` in the Python emitter. "10^-9" and "10⁻⁹" are the same exponent,
#' and a display written either way has to compare against the same number.
#' @noRd
mg_exponent <- function(plain, superscript) {
  if (nzchar(plain)) {
    return(plain)
  }
  if (!nzchar(superscript)) {
    return("")
  }
  from <- strsplit("⁰¹²³⁴⁵⁶⁷⁸⁹⁻⁺−", "")[[1]]
  to <- strsplit("0123456789-+-", "")[[1]]
  out <- strsplit(superscript, "")[[1]]
  matched <- match(out, from)
  out[!is.na(matched)] <- to[matched[!is.na(matched)]]
  paste(out, collapse = "")
}

#' The key fragment naming a second interval
#'
#' Mirrors `_level_slug` in the Python emitter, and must keep mirroring it: the same call in
#' either language has to produce the same keys, or a manuscript's bindings depend on which
#' language the analysis was written in. "90%" -> "90", "95% CrI" -> "95cri".
#' @noRd
mg_level_slug <- function(level) {
  slug <- tolower(gsub("[^0-9A-Za-z]", "", level))
  if (!nzchar(slug)) {
    stop(
      "level '", level, "' has no letters or digits to name a key with; use something ",
      "like '90%' or '95% CrI'",
      call. = FALSE
    )
  }
  slug
}

#' A cell that is a number written as text
#'
#' Mirrors `_NUMERIC_TEXT` in the Python emitter. This is the shape that used to slip
#' through there: `as.character()` accepted it, nothing compared it to anything, and a
#' hand-typed table number was indistinguishable from a computed one.
#' @noRd
mg_numeric_text <- function(text) {
  grepl("^\\s*[-+−]?[\\d,   ]*\\d(?:[.,]\\d+)?\\s*%?\\s*$", text, perl = TRUE) &&
    grepl("\\d", text)
}

#' Split a `{}` template into its literal pieces
#'
#' R has no `str.format`, so the same convention is implemented here rather than borrowing
#' a different one: a template written for one emitter has to mean the same in the other.
#' @noRd
mg_template_pieces <- function(template) {
  strsplit(template, "{}", fixed = TRUE)[[1]] -> pieces
  # strsplit drops a trailing empty piece; the count has to match the placeholders.
  wanted <- lengths(regmatches(template, gregexpr("{}", template, fixed = TRUE)))[[1]] + 1L
  length(pieces) <- wanted
  pieces[is.na(pieces)] <- ""
  pieces
}

#' A table cell composed from numbers
#'
#' `"77 (12.3)"` and `paste0(n, " (", pct, ")")` are the same string by the time `table()`
#' sees them, so no check can tell a computed cell from a typed one. The difference has to
#' be made at the API: hand over the numbers and a template, and the emitter formats them.
#'
#' Each part is a number, `list(number, digits)` when it needs rounding, or
#' `list(number, "<0.001")` when the number is not written as itself — the same three forms
#' the Python emitter takes, because a results fragment is a cross-language contract.
#'
#' @param template Text with `{}` where each number goes.
#' @param ... The numbers, in order.
#' @return An object `mg_table()` recognises as a composed cell.
#' @export
mg_cell <- function(template, ...) {
  parts <- list(...)
  pieces <- mg_template_pieces(template)
  if (length(pieces) != length(parts) + 1L) {
    stop(
      "cell template '", template, "' has ", length(pieces) - 1L, " placeholder(s) but ",
      length(parts), " value(s) were given",
      call. = FALSE
    )
  }
  structure(
    list(template = template, parts = parts, pieces = pieces),
    class = "mg_composed"
  )
}

#' Text the emitter itself assembled from structured data
#'
#' Mirrors `Verbatim` in the Python emitter: the one thing a cell can be that is neither a
#' number nor prose from the script. `code_list()` builds these by joining a list of codes it
#' was handed, so the cell is emitter output and carries the same exemption as a composed
#' cell. Not exported, which is what stops it becoming a way to type anything into a table.
#' @noRd
mg_verbatim <- function(text) structure(list(text = text), class = "mg_verbatim")

mg_git <- function(root, args) {
  out <- tryCatch(
    suppressWarnings(system2("git", c("-C", shQuote(root), args), stdout = TRUE, stderr = FALSE)),
    error = function(e) NULL
  )
  if (is.null(out) || length(out) == 0) NULL else trimws(paste(out, collapse = "\n"))
}

# Whether the value `parameter(key, ...)` hands back is read again by the script, after
# the Python emitter's `parameter_read`. FALSE when the call is a statement of its own or
# assigns a name no other line reads; TRUE when the name is read, or when the call sits inside
# a larger expression. NULL when the script cannot be parsed, the call is not found, or the
# value goes somewhere this does not follow: a list or an environment, or out of a block as
# its last expression. A name read again is all this establishes.
# Looser than the Python rule, and DESIGN.md says so: the name is looked for as a symbol
# anywhere in the file and not in the scope that assigned it, and a call with no braces
# round it, after `if (x)`, sits inside a larger expression.
mg_parameter_read <- function(path, key) {
  parsed <- tryCatch(parse(path, keep.source = TRUE), error = function(e) NULL)
  if (is.null(parsed)) return(NULL)
  pd <- utils::getParseData(parsed)
  if (is.null(pd) || nrow(pd) == 0) return(NULL)
  pd <- pd[order(pd$line1, pd$col1), , drop = FALSE]
  parent_of <- function(id) pd$parent[pd$id == id]
  children <- function(id) pd[pd$parent == id, , drop = FALSE]
  quoted <- c(sprintf('"%s"', key), sprintf("'%s'", key))
  calls <- integer()
  for (symbol in pd$id[pd$token == "SYMBOL_FUNCTION_CALL" & pd$text == "parameter"]) {
    call <- parent_of(parent_of(symbol))
    strings <- pd$id[pd$token == "STR_CONST" & pd$text %in% quoted]
    if (any(vapply(strings, function(s) parent_of(parent_of(s)) == call, logical(1)))) {
      calls <- c(calls, call)
    }
  }
  if (length(calls) != 1) return(NULL)
  call <- calls[[1]]
  around <- parent_of(call)
  if (around == 0) return(FALSE)
  siblings <- children(around)
  if ("'{'" %in% siblings$token) {
    # The last expression of a block is its value, which a function returns. A comment is
    # a row of the block too: one typed after the last expression made it not the last, and
    # a parameter a function returns was recorded as never read.
    exprs <- siblings$id[!siblings$terminal]
    return(if (utils::tail(exprs, 1) == call) NULL else FALSE)
  }
  arrows <- c("LEFT_ASSIGN", "EQ_ASSIGN", "RIGHT_ASSIGN")
  if (!any(siblings$token %in% arrows)) return(TRUE)
  exprs <- siblings$id[!siblings$terminal]
  rightwards <- "RIGHT_ASSIGN" %in% siblings$token
  value <- if (rightwards) exprs[[1]] else utils::tail(exprs, 1)
  if (value != call) return(TRUE)
  target <- if (rightwards) utils::tail(exprs, 1) else exprs[[1]]
  name <- children(target)
  if (nrow(name) != 1 || name$token != "SYMBOL") return(NULL)
  any(pd$token == "SYMBOL" & pd$text == name$text & pd$id != name$id)
}

# The first and last line of the code `step(name, { ... })` runs, read from the script as
# `mg_parameter_read` reads it: the expressions inside the braces, or the expression given.
# NULL when the script cannot be parsed or the call is not found once.
mg_step_lines <- function(path, name) {
  parsed <- tryCatch(parse(path, keep.source = TRUE), error = function(e) NULL)
  if (is.null(parsed)) return(NULL)
  pd <- utils::getParseData(parsed)
  if (is.null(pd) || nrow(pd) == 0) return(NULL)
  parent_of <- function(id) pd$parent[pd$id == id]
  quoted <- c(sprintf('"%s"', name), sprintf("'%s'", name))
  calls <- integer()
  for (symbol in pd$id[pd$token == "SYMBOL_FUNCTION_CALL" & pd$text == "step"]) {
    call <- parent_of(parent_of(symbol))
    strings <- pd$id[pd$token == "STR_CONST" & pd$text %in% quoted]
    if (any(vapply(strings, function(s) parent_of(parent_of(s)) == call, logical(1)))) {
      calls <- c(calls, call)
    }
  }
  if (length(calls) != 1) return(NULL)
  arguments <- pd[pd$parent == calls[[1]] & pd$token == "expr", , drop = FALSE]
  block <- arguments[order(arguments$line1, arguments$col1), , drop = FALSE]
  block <- block[nrow(block), , drop = FALSE]
  inside <- pd[pd$parent == block$id & !pd$terminal, , drop = FALSE]
  if (nrow(inside) > 0 && any(pd$parent == block$id & pd$token == "'{'")) {
    return(c(min(inside$line1), max(inside$line2)))
  }
  c(block$line1, block$line2)
}

# The code a step runs, and the functions it calls that the analysis defined itself (not a
# package's), followed through the functions they call, mirroring the Python `step_code`.
# Read as code, by deparsing: a comment or a re-wrapped line changes nothing.
mg_step_code <- function(expr, env) {
  follows <- character()
  waiting <- list(expr)
  while (length(waiting) > 0) {
    names <- all.names(waiting[[1]])
    waiting <- waiting[-1]
    for (n in setdiff(unique(names), follows)) {
      f <- get0(n, envir = env, mode = "function")
      if (is.null(f) || !is.function(f) || is.primitive(f)) next
      home <- environment(f)
      if (is.null(home) || isNamespace(home) || identical(home, baseenv())) next
      follows <- c(follows, n)
      waiting <- c(waiting, list(body(f)))
    }
  }
  follows <- sort(follows, method = "radix")
  shown <- function(x) paste(deparse(x, width.cutoff = 500L), collapse = "\n")
  text <- paste(c(shown(expr), vapply(follows, function(n) {
    paste0(n, " <- ", shown(get0(n, envir = env, mode = "function")))
  }, character(1))), collapse = "\n")
  list(digest = digest::digest(text, algo = "sha256", serialize = FALSE), follows = follows)
}

# What a variable can be meant to be, as the Python emitter has it.
mg_variable_kinds <- c("binary", "categorical", "ordinal", "continuous", "count")

# What the data hold of a variable: levels (where few), distinct values, missing. Sorted in
# code-point order, as Python sorts, whatever the locale.
mg_observed <- function(values, kind) {
  present <- unique(as.character(values[!is.na(values)]))
  present <- sort(present, method = "radix")
  out <- list(distinct = length(present), missing = sum(is.na(values)))
  if (kind %in% c("binary", "categorical", "ordinal") || length(present) <= 50) {
    out$levels <- I(present)
  }
  out
}

# The columns of the data a fit was made on, or NULL where there are none to name: a fit made
# from vectors in the environment, or on data that is no data frame or list. A glm keeps its
# data. An lm keeps only the call, so its `data` is read again where the formula was made.
mg_fit_columns <- function(fit) {
  data <- fit[["data"]]
  if (is.null(data) && !is.null(fit$call$data)) {
    data <- tryCatch(eval(fit$call$data, environment(stats::formula(fit))),
                     error = function(e) NULL)
  }
  if (is.list(data) && !is.null(names(data))) names(data) else NULL
}

# The data's columns an expression of a formula reads, as the Python emitter's
# `_variables_in` has them: `splines::ns(age, knots = knots)` reads age, and `knots` is an
# object of the script. Every name, as before, where the fit has no columns to compare with.
mg_variables_in <- function(expression, columns) {
  read <- all.vars(expression)
  if (is.null(columns)) read else read[read %in% columns]
}

# Whether an expression of a formula is a comparison, as the Python emitter's
# `_is_comparison` has it: known by its syntax, at the top of the expression, bare, in
# brackets or inside `I()`, and the negation of one. `factor(stage == "IV")` and
# `ifelse(age > 65, 1, 0)` are not: what the call around the comparison makes of it is not
# known from the syntax.
mg_is_comparison <- function(expression) {
  if (!is.call(expression) || !is.name(expression[[1]])) return(FALSE)
  called <- as.character(expression[[1]])
  if (called %in% c("==", "!=", "<", "<=", ">", ">=", "%in%")) return(length(expression) == 3)
  if (called %in% c("I", "(", "!")) {
    return(length(expression) == 2 && mg_is_comparison(expression[[2]]))
  }
  FALSE
}

# For a binomial fit, the events of each row and, for grouped data, the trials in all; NULL
# where neither can be read exactly. Grouped data are a response of two columns,
# `cbind(events, failures)`, read as the table holds them, or a proportion, whose trials R
# defines the prior weights to be. A proportion whose events or trials are not whole numbers
# is not a table of counts, and no events are recorded for it. The test is the one
# `binomial()` warns by.
mg_successes <- function(fit, frame) {
  response <- stats::model.response(frame)
  if (is.matrix(response) && ncol(response) == 2) {
    return(list(rows = response[, 1], trials = sum(response)))
  }
  y <- fit$y
  if (is.null(y)) return(NULL)  # fitted with y = FALSE: the fit kept no outcome to count
  if (all(y %in% c(0, 1))) return(list(rows = y, trials = NULL))
  weights <- fit$prior.weights
  whole <- function(v) all(abs(v - round(v)) <= 0.001)
  if (!whole(weights) || !whole(y * weights)) return(NULL)
  list(rows = round(y * weights), trials = sum(round(weights)))
}

# How many distinct values of `unit` the rows the model used hold, mirroring the Python
# emitter's `_units`. A glm keeps its data; an lm does not, and its data is found where the
# call names it. The rows used are the model frame's, `subset=` and the rows dropped for
# missing values both left out; a row with no unit is refused, as in Python.
mg_fit_units <- function(fit, unit) {
  data <- fit$data
  if (!is.data.frame(data)) {
    data <- tryCatch(
      eval(fit$call$data, environment(stats::formula(fit))),
      error = function(e) NULL
    )
  }
  if (!is.data.frame(data) || !(unit %in% names(data))) {
    stop("model: unit ", unit, " is not a column of the data the model was fitted on",
         call. = FALSE)
  }
  data <- as.data.frame(data)
  values <- data[rownames(stats::model.frame(fit)), unit, drop = TRUE]
  if (anyNA(values)) {
    stop("model: unit ", unit, " is missing in ", sum(is.na(values)), " of the rows the ",
         "model used, so how many units they hold cannot be counted", call. = FALSE)
  }
  list(column = unit, units = length(unique(values)))
}

# The model card of an lm or glm fit, read from the fit, mirroring the Python emitter's
# `read_statsmodels`. Facts only; the name a model goes by is derived when results are read.
# Whatever inherits from lm is read, so a fit built on glm (`MASS::glm.nb`) is too, with the
# family it gives itself, which the list of models may have no entry for.
mg_read_fit <- function(fit, unit = NULL) {
  if (!inherits(fit, "lm")) {
    stop("model: only lm and glm fits, and fits that inherit from them, are read, so the ",
         "terms cannot be read from this one", call. = FALSE)
  }
  tt <- stats::terms(fit)
  engine <- list(language = "R", package = "stats", class = class(fit)[[1]])
  if (inherits(fit, "glm")) {
    engine$family <- fit$family$family
    engine$link <- fit$family$link
  }
  factors <- attr(tt, "factors")
  xlevels <- fit$xlevels
  contrasts <- fit$contrasts
  binary <- identical(engine$family, "binomial")
  frame <- stats::model.frame(fit)
  columns <- mg_fit_columns(fit)
  counted <- if (binary) mg_successes(fit, frame) else NULL
  terms <- list()
  events_by_level <- list()
  for (label in attr(tt, "term.labels")) {
    used <- rownames(factors)[factors[, label] != 0]
    entered <- lapply(used, function(expression) {
      parsed <- str2lang(expression)
      record <- list(expression = expression, variables = I(mg_variables_in(parsed, columns)))
      if (!is.null(xlevels[[expression]])) {
        record$as <- "categorical"
        record$levels <- I(as.character(xlevels[[expression]]))
        coding <- contrasts[[expression]]
        if (is.null(coding) || identical(coding, "contr.treatment")) {
          record$reference <- as.character(xlevels[[expression]][[1]])
        }
      } else {
        record$as <- "numerical"
      }
      if (mg_is_comparison(parsed)) record$comparison <- TRUE
      record
    })
    if (!is.null(counted) && length(used) == 1 && !is.null(xlevels[[used[[1]]]])) {
      levels <- as.character(xlevels[[used[[1]]]])
      at <- factor(as.character(frame[[used[[1]]]]), levels = levels)
      sums <- tapply(counted$rows, at, sum)
      sums[is.na(sums)] <- 0
      for (variable in mg_variables_in(str2lang(used[[1]]), columns)) {
        events_by_level[[variable]] <- as.list(stats::setNames(as.integer(sums), levels))
      }
    }
    terms[[length(terms) + 1]] <- list(term = label, entered = entered)
  }
  left <- stats::formula(fit)[[2]]
  outcome <- list(
    expression = paste(deparse(left), collapse = " "),
    variables = I(mg_variables_in(left, columns))
  )
  if (mg_is_comparison(left)) outcome$comparison <- TRUE
  dropped <- length(fit$na.action)
  card <- list(
    engine = engine,
    formula = paste(deparse(stats::formula(fit)), collapse = " "),
    outcome = outcome,
    terms = terms,
    parameters = length(stats::coef(fit)) - attr(tt, "intercept"),
    n_input = stats::nobs(fit) + dropped,
    n_used = stats::nobs(fit),
    n_dropped = dropped,
    converged = if (inherits(fit, "glm")) isTRUE(fit$converged) else TRUE,
    # An lm or a glm keeps the standard errors its own model gives; sandwich estimators are
    # computed beside the fit, and nothing in it says so.
    covariance = "model-based",
    # The rows the fit used, by their labels, mirroring the Python `rows_digest`.
    rows_sha256 = digest::digest(paste(rownames(stats::model.frame(fit)), collapse = "\n"),
                                 algo = "sha256", serialize = FALSE)
  )
  if (!is.null(stats::model.offset(stats::model.frame(fit)))) card$offset <- TRUE
  if (!is.null(unit)) card$unit <- mg_fit_units(fit, unit)
  if (!is.null(counted)) {
    card$events <- as.integer(sum(counted$rows))
    if (!is.null(counted$trials)) card$trials <- as.integer(counted$trials)
    if (length(events_by_level) > 0) card$events_by_level <- events_by_level
  }
  card
}

# The MedDRA version `meddra_release.asc` states: the first `$`-separated field of its
# first line that is not blank, mirroring the Python `_meddra_release`. A file that does
# not open with a version is refused rather than read as one.
mg_meddra_release <- function(path) {
  lines <- readLines(path, warn = FALSE, encoding = "UTF-8")
  lines <- sub("^\ufeff", "", lines)
  line <- lines[nzchar(trimws(lines))][1]
  if (is.na(line)) line <- ""
  version <- trimws(strsplit(line, "$", fixed = TRUE)[[1]][1])
  if (is.na(version) || !grepl("^[0-9]+(\\.[0-9]+)?$", version)) {
    stop(basename(path), ": its first line, ", substr(line, 1, 40),
         ", does not open with a MedDRA version", call. = FALSE)
  }
  version
}

# Keep the plan as it stands the first time the analysis writes results, and never again,
# mirroring the Python emitter's `freeze_plan`: design/plan.frozen.yaml holds the plan's
# text, its digest, the day and the script, written as JSON, which is YAML too.
mg_freeze_plan <- function(project_root, script) {
  plan <- file.path(project_root, "design", "plan.md")
  frozen <- file.path(project_root, "design", "plan.frozen.yaml")
  if (!file.exists(plan) || file.exists(frozen)) return(invisible(NULL))
  stamp <- format(Sys.time(), "%Y-%m-%dT%H:%M:%S%z", tz = "UTC")
  stamp <- sub("([+-]\\d{2})(\\d{2})$", "\\1:\\2", stamp)
  # A plan that is not UTF-8 text, or holds a NUL as a UTF-16 one does, is not kept, as in
  # Python: rawToChar() stops on a NUL, after the results were written (round 1 of #271).
  bytes <- readBin(plan, "raw", file.info(plan)$size)
  if (any(bytes == as.raw(0))) return(invisible(NULL))
  text <- rawToChar(bytes)
  Encoding(text) <- "UTF-8"
  if (!validUTF8(text)) return(invisible(NULL))
  record <- list(
    schema = "manuscript-guard/plan-frozen/1",
    frozen_at = stamp,
    by = script,
    sha256 = mg_source_digest(plan),
    plan = text
  )
  json <- jsonlite::toJSON(record, auto_unbox = TRUE, pretty = 2)
  mg_write_lf(as.character(json), frozen)
  invisible(frozen)
}

#' Create a results emitter
#'
#' The only supported way for an R analysis to publish a number.
#'
#' @param script Path to the analysis script. Inside a script, pass its own path.
#' @param inputs Character vector of data files read, project-relative or absolute.
#' @param root Project root. Detected from `script` when omitted.
#' @return A list of functions: `value()`, `interval()`, `cell()`, `table()`, `code_list()`,
#'   `add_input()`, `write()`.
#' @examples
#' \dontrun{
#' em <- mg_emitter("analysis/01_model.R", inputs = "data/reports.csv")
#' em$value("cohort.n_reports", 4000L)
#' em$interval("ror", 3.8439, 2.1032, 7.0210, digits = 2)
#' em$write()
#' }
#' @export
mg_emitter <- function(script, inputs = character(), root = NULL) {
  script_path <- normalizePath(script, winslash = "/", mustWork = TRUE)
  project_root <- if (is.null(root)) mg_find_root(dirname(script_path)) else normalizePath(root, winslash = "/")
  state <- new.env(parent = emptyenv())
  state$values <- list()
  state$inputs <- as.character(inputs)
  state$restricted <- character()
  state$synthetic <- character()
  state$tables <- list()
  state$code_lists <- list()
  state$variables <- list()
  state$models <- list()
  state$steps <- list()
  state$corrections <- list()
  # Which cells this emitter produced from numbers, per table, in the shape the fragment
  # publishes. G2 reads it and applies the same rule to a fragment from either language;
  # without it, a composed cell and a typed one are the same characters on disk.
  state$composed <- list()

  relative <- function(path) {
    full <- normalizePath(path, winslash = "/", mustWork = TRUE)
    prefix <- paste0(project_root, "/")
    if (startsWith(full, prefix)) substring(full, nchar(prefix) + 1L) else full
  }

  # `of`, `over` and `family` say what a statistic that means nothing alone belongs to,
  # mirroring the Python `value()`: a p value names its estimate with `of` and its family of
  # tests with `family`; a share names its numerator with `of` and its denominator with
  # `over`. G2 warns on a sentence that quotes it without them.
  value <- function(key, value, display = NULL, digits = NULL, unit = NULL,
                    quoted = TRUE, note = NULL, bounds = NULL, bound = NULL,
                    level = NULL, of = NULL, over = NULL, family = NULL) {
    if (!is.null(state$values[[key]])) {
      stop(key, " emitted twice by ", script_path, call. = FALSE)
    }
    if (is.null(bounds) && !is.null(level)) {
      stop(key, " declares a level without being a bound of anything", call. = FALSE)
    }
    if (identical(of, key) || identical(over, key)) {
      stop(key, " declares itself as what it belongs to", call. = FALSE)
    }
    if (!is.null(over) && is.null(of)) {
      stop(key, ": a share names its numerator with `of` beside its denominator `over`",
           call. = FALSE)
    }
    if (!is.null(family) && (is.null(of) || !is.null(over))) {
      stop(key, ": a family is of p values, each naming its estimate with `of` and no `over`",
           call. = FALSE)
    }
    shown <- mg_display(key, value, display, digits)
    entry <- list(value = value, display = shown)
    if (!is.null(digits)) entry$digits <- as.integer(digits)
    if (!is.null(unit)) entry$unit <- unit
    if (!isTRUE(quoted)) entry$quoted <- FALSE
    if (!is.null(note)) entry$note <- note
    if (!is.null(bounds)) entry$bounds <- bounds
    if (!is.null(bound)) entry$bound <- match.arg(bound, c("low", "high"))
    if (!is.null(level)) entry$level <- level
    if (!is.null(of)) entry$of <- of
    if (!is.null(over)) entry$over <- over
    if (!is.null(family)) entry$family <- family
    state$values[[key]] <- entry
    invisible(NULL)
  }

  # Declare how a family of p values is corrected for multiple comparisons, mirroring the
  # Python `correction()`. "none" is a declaration too, and needs its reason.
  correction <- function(family, method, reason = NULL) {
    if (!nzchar(family) || !nzchar(method)) {
      stop("correction: a family and a method, both named", call. = FALSE)
    }
    if (!is.null(state$corrections[[family]])) {
      stop("correction for ", family, " declared twice by ", script_path, call. = FALSE)
    }
    if (tolower(trimws(method)) == "none" && (is.null(reason) || !nzchar(reason))) {
      stop("correction for ", family, ": 'none' is a decision, and needs its reason",
           call. = FALSE)
    }
    entry <- list(method = method)
    if (!is.null(reason)) entry$reason <- reason
    state$corrections[[family]] <- entry
    invisible(NULL)
  }

  # Record a choice the analysis made, and hand it back for the analysis to use, mirroring
  # the Python `parameter()`:
  #
  #   alpha <- em$parameter("alpha", 0.05)
  #   z <- qnorm(1 - alpha / 2)
  #
  # Writes `param.alpha`, which the Methods quote as {{results.param.alpha}}. The script is
  # read where the call stands, and the fragment records whether the value handed back is
  # read again: declared is not used, and G2 fails a parameter never read.
  parameter <- function(key, value, display = NULL, digits = NULL, unit = NULL,
                        note = NULL) {
    if (!grepl("^[a-z0-9_]+(\\.[a-z0-9_]+)*$", key)) {
      stop("parameter ", key, ": a key is lowercase letters, digits and underscores, in ",
           "parts joined by dots, so that the Methods can bind it", call. = FALSE)
    }
    full <- paste0("param.", key)
    # Written as typed, as the Python emitter writes it: a threshold is not rounded.
    if (is.double(value) && is.null(display) && is.null(digits)) {
      display <- trimws(formatC(value, digits = 15, format = "g"))
    }
    value(full, value, display = display, digits = digits, unit = unit, note = note)
    state$values[[full]]$role <- "parameter"
    read <- mg_parameter_read(script_path, key)
    if (!is.null(read)) state$values[[full]]$read <- read
    invisible(value)
  }

  # Mark the code a Methods claim describes, run it, and record that it ran, mirroring the
  # Python `step()`:
  #
  #   em$step("ci", {
  #     se <- sqrt(1 / a + 1 / b + 1 / c + 1 / d)
  #     low <- exp(log(ror) - z * se)
  #   })
  #
  # The code runs where the call stands, as if the braces were not there. The Methods point
  # at it with {{method.ci}}. The fragment records its lines and a digest of its code, read
  # as code, with the functions it calls that the analysis defined itself.
  step <- function(name, code) {
    if (!grepl("^[a-z][a-z0-9_]*(\\.[a-z0-9_]+)*$", name)) {
      stop("step ", name, ": a name is lowercase letters, digits and underscores, starting ",
           "with a letter, in parts joined by dots, so that the Methods can bind it",
           call. = FALSE)
    }
    expr <- substitute(code)
    env <- parent.frame()
    read <- mg_step_code(expr, env)
    record <- list()
    lines <- mg_step_lines(script_path, name)
    if (!is.null(lines)) record$lines <- as.integer(lines)
    record$digest <- read$digest
    if (length(read$follows) > 0) record$follows <- I(read$follows)
    if (!is.null(state$steps[[name]]) && !identical(state$steps[[name]], record)) {
      stop("step ", name, " marks two different blocks of code", call. = FALSE)
    }
    state$steps[[name]] <- record
    invisible(eval(expr, env))
  }

  # The version of a piece of software this run used, as the run found it, mirroring the
  # Python `software()`. "R" is the interpreter; any other name must be a package this
  # session has loaded, because the Methods would otherwise name software that computed
  # nothing.
  software <- function(name) {
    if (identical(name, "R")) {
      version <- paste(R.version$major, R.version$minor, sep = ".")
    } else {
      if (!(name %in% loadedNamespaces())) {
        stop("software ", name, ": this session has not loaded it, so it computed none ",
             "of these results", call. = FALSE)
      }
      version <- as.character(utils::packageVersion(name))
    }
    key <- paste0("software.", gsub("[^a-z0-9_]", "_", tolower(name)))
    if (!is.null(state$values[[key]])) {
      stop(key, " emitted twice by ", script_path, call. = FALSE)
    }
    state$values[[key]] <- list(value = version, display = version, label = TRUE,
                                role = "software")
    invisible(version)
  }

  # A coding dictionary the analysis coded with, and its release, mirroring the Python
  # `dictionary()`. A file named is digested as an input; MedDRA's `meddra_release.asc`
  # states its version as the first `$`-separated field of its first line, and is read.
  dictionary <- function(name, release = NULL, release_file = NULL) {
    if (!grepl("[A-Za-z]", name)) {
      stop("dictionary ", name, ": a dictionary is named by its name", call. = FALSE)
    }
    if (!is.null(release) && !is.character(release)) {
      # A number has no digits of its own: 27.0 is "27" here and "27.0" in Python.
      stop("dictionary ", name, ": give the release as text, as the dictionary writes it ",
           "(\"27.0\", not 27.0)", call. = FALSE)
    }
    read <- NULL
    if (!is.null(release_file)) {
      full <- if (file.exists(release_file)) release_file else file.path(project_root, release_file)
      if (!file.exists(full) || dir.exists(full)) {
        stop("dictionary ", name, ": no file ", release_file, call. = FALSE)
      }
      if (identical(tolower(basename(full)), "meddra_release.asc")) {
        read <- mg_meddra_release(full)
      }
      add_input(release_file)
    }
    given <- NULL
    if (!is.null(release)) {
      given <- trimws(gsub("[[:space:]]+", " ", as.character(release)))
    }
    if (!is.null(given) && !is.null(read) && !identical(given, read)) {
      stop("dictionary ", name, ": release ", given, " was given, and ", basename(full),
           " says ", read, call. = FALSE)
    }
    version <- if (!is.null(read)) read else given
    if (is.null(version) || !nzchar(version)) {
      stop("dictionary ", name, ": give its release, or the file that states it", call. = FALSE)
    }
    key <- paste0("dictionary.", gsub("[^a-z0-9_]", "_", tolower(name)))
    if (!is.null(state$values[[key]])) {
      stop(key, " emitted twice by ", script_path, call. = FALSE)
    }
    state$values[[key]] <- list(value = version, display = version, label = TRUE,
                                role = "dictionary")
    invisible(version)
  }

  # Declare a variable a model uses, with the kind it is meant to be, mirroring the Python
  # `variable()`. The data cannot say whether 1 to 4 is a grade, a code or a count.
  variable <- function(name, kind, label, levels = NULL, reference = NULL, unit = NULL,
                       values = NULL) {
    if (!(kind %in% mg_variable_kinds)) {
      stop("variable ", name, ": kind is one of ", paste(mg_variable_kinds, collapse = ", "),
           call. = FALSE)
    }
    if (!is.null(state$variables[[name]])) {
      stop("variable ", name, " declared twice by ", script_path, call. = FALSE)
    }
    entry <- list(kind = kind, label = label)
    if (!is.null(levels)) entry$levels <- I(as.character(levels))
    if (!is.null(reference)) {
      entry$reference <- as.character(reference)
      if (!is.null(levels) && !(entry$reference %in% entry$levels)) {
        stop("variable ", name, ": reference ", reference, " is not a level", call. = FALSE)
      }
    }
    if (!is.null(unit)) entry$unit <- unit
    if (!is.null(values)) entry$observed <- mg_observed(values, kind)
    state$variables[[name]] <- entry
    invisible(NULL)
  }

  # Record a fitted model as the fit describes it, mirroring the Python `model()`.
  # `unit` names the column of the data whose values the rows belong to, mirroring the
  # Python `model()`: G15 warns where there are more rows than units and the fit is neither
  # cluster-robust nor mixed.
  model <- function(key, fit, name, description = NULL, unit = NULL) {
    if (!grepl("^[a-z][a-z0-9_]*$", key)) {
      stop("model ", key, ": a key is lowercase letters, digits and underscores, so that ",
           "its values and its table can be bound", call. = FALSE)
    }
    if (!is.null(state$models[[key]])) {
      stop("model ", key, " recorded twice by ", script_path, call. = FALSE)
    }
    card <- mg_read_fit(fit, unit)
    card$name <- name
    if (!is.null(description)) card$description <- description
    state$models[[key]] <- card
    invisible(NULL)
  }

  # Publish an estimate and its interval as one thing, mirroring the Python `interval()`.
  #
  # R had only `value()`, so the one sentence a disproportionality paper exists to carry - an
  # estimate with its interval - was the sentence an R analysis could not express. Three keys
  # named point, ci_low and ci_high are three unrelated numbers to every gate unless the
  # fragment records which end each bound is, which is what lets G2 refuse an interval quoted
  # backwards. The results file is a cross-language contract, and a rule enforced on one side
  # only is a rule an author steps around by switching language.
  #
  # A second interval on the same estimate - a 90% CI beside the 95%, a credibility interval
  # beside a frequentist one - is named by its `level`, and reuses the estimate rather than
  # publishing it twice:
  #
  #   em$interval("ror", 3.8439, 2.1032, 7.0210, digits = 2)
  #   em$interval("ror", low = 2.5104, high = 5.8722, level = "90%", digits = 2)
  interval <- function(key, point = NULL, low = NULL, high = NULL, level = NULL,
                       digits = NULL, unit = NULL, quoted = TRUE) {
    if (is.null(low) || is.null(high)) {
      stop(key, ": an interval needs both `low` and `high`", call. = FALSE)
    }
    point_key <- paste0(key, ".point")
    if (is.null(point)) {
      if (is.null(state$values[[point_key]])) {
        stop(
          key, ": no `point` given and ", point_key, " has not been emitted. Publish the ",
          "estimate with its first interval, then add further levels",
          call. = FALSE
        )
      }
      point <- state$values[[point_key]]$value
    } else {
      value(point_key, point, digits = digits, unit = unit, quoted = quoted)
    }
    if (!(low <= point && point <= high)) {
      stop(
        key, ": the interval does not bracket the estimate - ", format(low), " to ",
        format(high), " around ", format(point), ". Check the order of the arguments",
        call. = FALSE
      )
    }
    stem <- if (is.null(level)) "ci" else paste0("ci", mg_level_slug(level))
    value(
      paste0(key, ".", stem, "_low"), low, digits = digits, unit = unit, quoted = quoted,
      bounds = point_key, bound = "low", level = level
    )
    value(
      paste0(key, ".", stem, "_high"), high, digits = digits, unit = unit, quoted = quoted,
      bounds = point_key, bound = "high", level = level
    )
    invisible(NULL)
  }

  # Column headers are recorded with no `row`, matching the fragment schema and the Python
  # emitter's internal keying.
  HEADER <- -2L

  format_cell <- function(key, row, column, cell, digits) {
    where <- paste0("table '", key, "' row ", row, " column ", column)
    record <- function(template, parts) {
      entry <- list(column = as.integer(column), template = template)
      if (!identical(row, HEADER)) entry$row <- as.integer(row)
      if (length(parts) > 0) entry$parts <- as.list(as.character(parts))
      state$composed[[key]] <- c(state$composed[[key]], list(entry))
    }

    if (inherits(cell, "mg_composed")) {
      shown <- vapply(
        seq_along(cell$parts),
        function(i) {
          part <- cell$parts[[i]]
          if (is.list(part)) {
            second <- part[[2]]
            if (is.character(second)) {
              mg_display(where, part[[1]], second, NULL)
            } else {
              mg_display(where, part[[1]], NULL, second)
            }
          } else {
            mg_display(where, part, NULL, NULL)
          }
        },
        character(1)
      )
      text <- paste0(cell$pieces, c(shown, ""), collapse = "")
      # The literal is the template with its placeholders removed: the part the script
      # typed, checked like any other text. Without it, "{} (n = 412)" would smuggle a
      # count into the table under the exemption the composed cell carries.
      record(cell$template, shown)
      return(text)
    }
    if (inherits(cell, "mg_verbatim")) {
      # Recorded as a code-list cell, not as a composed one. Rebuilding it from its own
      # declared part proves nothing - the part would be the text - so the gate checks it
      # against the code list published in the same fragment. Matches the Python emitter.
      entry <- list(column = as.integer(column), template = "", codes = TRUE)
      if (!identical(row, HEADER)) entry$row <- as.integer(row)
      state$composed[[key]] <- c(state$composed[[key]], list(entry))
      return(cell$text)
    }
    if (is.logical(cell)) {
      return(if (isTRUE(cell)) "TRUE" else "FALSE")
    }
    if (is.numeric(cell)) {
      wanted <- if (is.list(digits)) digits[[as.character(column)]] else digits
      shown <- mg_display(where, cell, NULL, wanted)
      # Recorded like a composed cell, because that is what it is: a number the emitter
      # formatted. Only the emitter knows that, so without the record a plain numeric cell
      # is indistinguishable from a typed one the moment anyone reads the file.
      record("{}", shown)
      return(shown)
    }
    if (is.character(cell)) {
      if (mg_numeric_text(cell)) {
        stop(
          where, ": '", cell, "' is a number written as text. Pass the number itself so it ",
          "is formatted here and traceable to this analysis; a numeric string is typed by ",
          "hand and compared to nothing",
          call. = FALSE
        )
      }
      return(cell)
    }
    stop(where, ": cells must be numbers or text", call. = FALSE)
  }

  #' Record a table. Cells are formatted here rather than in the manuscript.
  table_ <- function(key, columns, rows, caption = NULL, align = NULL,
                     quoted = TRUE, digits = NULL) {
    if (!is.null(state$tables[[key]])) {
      stop("table '", key, "' emitted twice by ", script_path, call. = FALSE)
    }
    width <- length(columns)
    for (i in seq_along(rows)) {
      if (length(rows[[i]]) != width) {
        stop(
          "table '", key, "': row ", i - 1L, " has ", length(rows[[i]]),
          " cells, header has ", width,
          call. = FALSE
        )
      }
    }

    header <- vapply(
      seq_along(columns),
      function(c) format_cell(key, HEADER, c - 1L, columns[[c]], NULL),
      character(1)
    )
    body <- lapply(seq_along(rows), function(r) {
      as.list(vapply(
        seq_along(rows[[r]]),
        function(c) format_cell(key, r - 1L, c - 1L, rows[[r]][[c]], digits),
        character(1)
      ))
    })

    spec <- list(columns = as.list(header), rows = body)
    if (!is.null(caption)) spec$caption <- caption
    if (!is.null(align)) {
      if (length(align) != width) {
        stop("table '", key, "': align has ", length(align), " entries, need ", width,
             call. = FALSE)
      }
      spec$align <- as.list(as.character(align))
    }
    if (!isTRUE(quoted)) spec$quoted <- FALSE
    state$tables[[key]] <- spec
    invisible(NULL)
  }

  #' The table of codes RECORD 6.1 asks for, built from the lists the analysis used.
  code_list <- function(key, entries, caption = NULL,
                        columns = c("Concept", "Coding system", "Codes")) {
    rows <- vector("list", length(entries))
    structured <- vector("list", length(entries))
    for (i in seq_along(entries)) {
      entry <- entries[[i]]
      missing <- setdiff(c("concept", "system", "codes"), names(entry))
      if (length(missing) > 0) {
        stop("code list '", key, "' entry ", i - 1L, ": missing ",
             paste(sort(missing), collapse = ", "), call. = FALSE)
      }
      codes <- as.character(entry$codes)
      if (length(codes) == 0) {
        stop(
          "code list '", key, "' entry ", i - 1L, ": no codes. An empty list published as a ",
          "definition says the concept matched nothing, which is a finding, not a ",
          "formatting choice",
          call. = FALSE
        )
      }
      # Joined here rather than by the caller, which is what makes the cell emitter output
      # rather than the script's prose - the same bargain as a composed cell.
      rows[[i]] <- list(
        as.character(entry$concept),
        as.character(entry$system),
        mg_verbatim(paste(codes, collapse = ", "))
      )
      structured[[i]] <- list(
        concept = as.character(entry$concept),
        system = as.character(entry$system),
        codes = as.list(codes)
      )
    }
    table_(key, as.character(columns), rows, caption = caption)
    state$code_lists[[key]] <- structured
    invisible(NULL)
  }

  # `restricted` says the data custodian forbids the file leaving their hands: G1 then fails
  # while git tracks it. `synthetic` says it is not the real data, a simulation, a dummy
  # extract or a test fixture: G1 then says so of every result the manuscript quotes from
  # this run, and fails at submission.
  add_input <- function(path, restricted = FALSE, synthetic = FALSE) {
    # One path or several, as `list.files()` gives them; one already declared is not listed twice.
    state$inputs <- c(state$inputs, setdiff(as.character(path), state$inputs))
    if (isTRUE(restricted)) state$restricted <- c(state$restricted, path)
    if (isTRUE(synthetic)) state$synthetic <- c(state$synthetic, path)
    invisible(NULL)
  }

  provenance <- function() {
    input_records <- lapply(state$inputs, function(path) {
      full <- if (file.exists(path)) path else file.path(project_root, path)
      if (!file.exists(full)) stop("declared input does not exist: ", full, call. = FALSE)
      record <- list(
        path = relative(full),
        sha256 = mg_input_digest(full),
        bytes = as.integer(file.info(full)$size)
      )
      if (path %in% state$restricted) record$restricted <- TRUE
      if (path %in% state$synthetic) record$synthetic <- TRUE
      record
    })

    sha <- mg_git(project_root, c("rev-parse", "HEAD"))
    vcs <- list()
    if (!is.null(sha)) {
      vcs$sha <- sha
      vcs$dirty <- !is.null(mg_git(project_root, c("status", "--porcelain")))
      branch <- mg_git(project_root, c("rev-parse", "--abbrev-ref", "HEAD"))
      if (!is.null(branch)) vcs$branch <- branch
    }

    packages <- vapply(
      sessionInfo()$otherPkgs,
      function(p) as.character(p$Version),
      character(1)
    )

    session <- list(
      language = "R",
      version = paste(R.version$major, R.version$minor, sep = "."),
      platform = R.version$platform
    )
    # An empty R list serialises as [], and the schema asks for an object here. Omitting
    # the key is both valid and more honest than writing an empty container.
    if (length(packages) > 0) session$packages <- as.list(packages)

    # The packages the analysis ran with, as the project's lockfiles pin them, mirroring the
    # Python emitter's `environment`, in the same order: by name, as bytes compare. G1 says
    # when one changed after the results were written.
    # Listed, not globbed: a root whose path holds brackets, "Study [2024]", is no pattern.
    lock_paths <- unique(c(
      file.path(project_root, c("renv.lock", "uv.lock", "poetry.lock", "environment.yml")),
      file.path(project_root, list.files(project_root, pattern = "^requirements.*\\.txt$"))
    ))
    lock_paths <- lock_paths[file.exists(lock_paths) & !dir.exists(lock_paths)]
    lock_paths <- lock_paths[order(basename(lock_paths), method = "radix")]
    environment <- lapply(lock_paths, function(path) {
      # Line endings left out, as Python's `lockfile_digest`: see the Python emitter.
      list(path = relative(path), sha256 = mg_lockfile_digest(path))
    })

    # "+0900" is not RFC 3339; the offset needs its colon.
    stamp <- format(Sys.time(), "%Y-%m-%dT%H:%M:%S%z")
    stamp <- sub("([+-]\\d{2})(\\d{2})$", "\\1:\\2", stamp)

    provenance <- list(
      generated_by = relative(script_path),
      # Mirrors the Python emitter. G1 compares this rather than modification times,
      # because an mtime is set by `touch`. Line-ending-normalised, like Python's
      # `source_digest`: git rewrites line endings on checkout, and CRLF instead of LF
      # cannot change what a script computed. Hashing raw bytes made G1 report
      # `script-newer` for a script nobody had touched. The two emitters have to agree
      # here, or an R-written fragment and a Python-written one describe the same file
      # differently.
      generated_by_sha256 = mg_source_digest(script_path),
      generated_at = stamp,
      tool = list(name = "manuscriptguard", version = "0.1.0"),
      inputs = input_records,
      environment = environment,
      session = session
    )
    if (length(vcs) > 0) provenance$vcs <- vcs
    provenance
  }

  write <- function(path = NULL) {
    if (is.null(path)) {
      dir.create(file.path(project_root, "results"), showWarnings = FALSE, recursive = TRUE)
      stem <- sub("\\.[Rr]$|\\.[Rr]md$|\\.qmd$", "", basename(script_path))
      path <- file.path(project_root, "results", paste0(stem, ".json"))
    } else if (!grepl("^([A-Za-z]:)?[/\\\\]", path)) {
      path <- file.path(project_root, path)
    }
    dir.create(dirname(path), showWarnings = FALSE, recursive = TRUE)

    document <- list(
      schema = "manuscript-guard/results/1",
      provenance = provenance(),
      values = state$values
    )
    if (length(state$tables) > 0) {
      document$tables <- lapply(names(state$tables), function(key) {
        spec <- state$tables[[key]]
        entries <- state$composed[[key]]
        if (length(entries) > 0) spec$composed <- entries
        spec
      })
      names(document$tables) <- names(state$tables)
    }
    if (length(state$code_lists) > 0) document$code_lists <- state$code_lists
    if (length(state$variables) > 0) document$variables <- state$variables
    if (length(state$models) > 0) document$models <- state$models
    if (length(state$steps) > 0) document$steps <- state$steps
    if (length(state$corrections) > 0) document$corrections <- state$corrections
    json <- jsonlite::toJSON(document, auto_unbox = TRUE, pretty = 2, digits = NA, null = "null")
    mg_write_lf(as.character(json), path)

    # The sidecar digest, byte-identical in intent to the Python emitter's: hash the file
    # you just wrote, so a later hand-edit cannot pass unnoticed.
    checksum <- digest::digest(file = path, algo = "sha256")
    mg_write_lf(paste0(checksum, "  ", basename(path)), paste0(path, ".sha256"))
    mg_freeze_plan(project_root, relative(script_path))
    invisible(path)
  }

  list(
    value = value,
    correction = correction,
    parameter = parameter,
    software = software,
    dictionary = dictionary,
    variable = variable,
    model = model,
    step = step,
    interval = interval,
    cell = mg_cell,
    table = table_,
    code_list = code_list,
    add_input = add_input,
    write = write
  )
}
