(function (global) {
  "use strict";

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function katexLib(explicit) {
    if (explicit) return explicit;
    if (typeof katex !== "undefined" && katex && katex.renderToString) return katex;
    if (global.katex && global.katex.renderToString) return global.katex;
    return null;
  }

  /** Same delimiter order as teaching-shell renderMathMarkdown. */
  function renderMathMarkdown(src, katexImpl) {
    var placeholders = [];
    function stash(tex, display) {
      var i = placeholders.length;
      placeholders.push({ tex: tex, display: display });
      return "@@MATH" + i + "@@";
    }
    var text = String(src || "");
    text = text.replace(/\$\$([\s\S]+?)\$\$/g, function (_, tex) {
      return stash(String(tex).trim(), true);
    });
    text = text.replace(/\\\[([\s\S]+?)\\\]/g, function (_, tex) {
      return stash(String(tex).trim(), true);
    });
    text = text.replace(/\\\(([\s\S]+?)\\\)/g, function (_, tex) {
      return stash(String(tex).trim(), false);
    });
    text = text.replace(/\$([^$\n]+?)\$/g, function (_, tex) {
      return stash(String(tex).trim(), false);
    });
    var html = esc(text);
    html = html.replace(/^###\s+(.+)$/gm, "<h3>$1</h3>");
    html = html.replace(/^##\s+(.+)$/gm, "<h2>$1</h2>");
    html = html.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
    html = html.replace(/`([^`]+)`/g, "<code>$1</code>");
    html = html.replace(/\n{2,}/g, "</p><p>");
    html = "<p>" + html + "</p>";
    var K = katexLib(katexImpl);
    html = html.replace(/@@MATH(\d+)@@/g, function (_, idx) {
      var item = placeholders[Number(idx)];
      if (!item || !K) return "<code>" + esc(item ? item.tex : "") + "</code>";
      try {
        return K.renderToString(item.tex, {
          displayMode: !!item.display,
          throwOnError: false,
          strict: "ignore",
          trust: false
        });
      } catch (e) {
        return "<code>" + esc(item.tex) + "</code>";
      }
    });
    return html;
  }

  function renderMathTitle(src, katexImpl) {
    var html = renderMathMarkdown(src, katexImpl);
    if (html.indexOf("</p><p>") < 0 && html.slice(0, 3) === "<p>" && html.slice(-4) === "</p>") {
      return html.slice(3, -4);
    }
    return html;
  }

  // Same spans as renderMathMarkdown. Do not strip a heading that ends inside one.
  function prefixCutsMath(text, cut) {
    text = String(text || "");
    cut = cut | 0;
    if (cut <= 0 || cut >= text.length) return false;
    var patterns = [
      /\$\$[\s\S]+?\$\$/g,
      /\\\[[\s\S]+?\\\]/g,
      /\\\([\s\S]+?\\\)/g,
      /\$[^$\n]+?\$/g
    ];
    var occupied = new Array(text.length);
    for (var p = 0; p < patterns.length; p++) {
      var match;
      var re = patterns[p];
      while ((match = re.exec(text))) {
        var start = match.index;
        var end = start + match[0].length;
        var overlap = false;
        for (var i = start; i < end; i++) {
          if (occupied[i]) { overlap = true; break; }
        }
        if (overlap) continue;
        if (start < cut && cut < end) return true;
        for (var j = start; j < end; j++) occupied[j] = true;
      }
    }
    return false;
  }

  function renderStemHtml(item, katexImpl) {
    var stem = (item && item.stem) || "";
    var title = (item && item.title) || "";
    if (title && stem.indexOf(title) === 0 && !prefixCutsMath(stem, title.length)) {
      var rest = stem.slice(title.length).replace(/^[\s：:·。.\-—]+/, "");
      if (rest) stem = rest;
    }
    var html = '<div class="stem-body" data-od-id="item-stem">' + renderMathMarkdown(stem, katexImpl) + "</div>";
    var opts = (item && item.options) || [];
    if (opts.length) {
      html += '<ol class="mcq-options" data-od-id="item-options">';
      opts.forEach(function (o) {
        html +=
          '<li><span class="mcq-letter">' +
          esc(o.letter) +
          "</span><div>" +
          renderMathMarkdown(o.text || "", katexImpl) +
          "</div></li>";
      });
      html += "</ol>";
    } else if (item && item.katex && !/\$|\\\[|\\\(/.test(stem)) {
      html +=
        '<div class="math-block" data-od-id="katex-formula" data-tex="' +
        esc(item.katex) +
        '"></div>';
    }
    return html;
  }

  function hasMathDelimiters(src) {
    return /\$\$|\\\[|\\\(|\$[^$\n]/.test(String(src || ""));
  }

  global.FqmMath = {
    esc: esc,
    renderMathMarkdown: renderMathMarkdown,
    renderMathTitle: renderMathTitle,
    renderStemHtml: renderStemHtml,
    prefixCutsMath: prefixCutsMath,
    hasMathDelimiters: hasMathDelimiters
  };
})(typeof window !== "undefined" ? window : globalThis);
