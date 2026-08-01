import type { Root, RootContent, Text } from "mdast";

const WIKILINK_RE = /\[\[([^\]\:;]+)\]\]/g;

/**
 * Custom remark plugin that parses `[[Name]]` wikilinks in Markdown body text.
 *
 * Transforms matched wikilinks into standard `link` MDAST nodes with a
 * `wiki://` URL scheme. react-markdown renders these as `<a>` tags, and the
 * MarkdownViewer's custom `a` component handler intercepts `wiki://` hrefs
 * to render the WikiLink atom.
 *
 * Regex explicitly rejects colons (`:`) and semicolons (`;`) per spec WR4
 * to avoid false positives on frontmatter formats like `[[Ver ficha: X]]`.
 *
 * Code blocks and inline code are naturally skipped — they have `value`
 * strings, not `children` arrays, so the tree walker never enters them.
 */
export function remarkWikiLink() {
  return (tree: Root) => {
    transformNode(tree);
  };
}

function transformNode(node: { children?: unknown[] }): void {
  if (!node.children || !Array.isArray(node.children)) return;

  const newChildren: RootContent[] = [];
  for (const child of node.children as RootContent[]) {
    if (child.type === "text") {
      newChildren.push(...splitWikilinks(child as Text));
    } else {
      if ("children" in child && Array.isArray(child.children)) {
        transformNode(child as { children?: unknown[] });
      }
      newChildren.push(child);
    }
  }
  node.children = newChildren;
}

function splitWikilinks(textNode: Text): RootContent[] {
  const value = textNode.value;
  const result: RootContent[] = [];
  let lastIndex = 0;

  // Fresh regex instance to avoid stale lastIndex across calls
  const regex = new RegExp(WIKILINK_RE.source, "g");
  let match: RegExpExecArray | null;

  while ((match = regex.exec(value)) !== null) {
    // Text before the match
    if (match.index > lastIndex) {
      result.push({
        type: "text",
        value: value.slice(lastIndex, match.index),
      });
    }

    // Wikilink becomes a standard link node with wiki:// URL scheme
    const name = match[1];
    result.push({
      type: "link",
      url: `wiki://${name}`,
      title: null,
      children: [
        {
          type: "text",
          value: name,
        },
      ],
    });

    lastIndex = match.index + match[0].length;
  }

  // Trailing text after last match
  if (lastIndex < value.length) {
    result.push({
      type: "text",
      value: value.slice(lastIndex),
    });
  }

  return result.length > 0 ? result : [textNode];
}
