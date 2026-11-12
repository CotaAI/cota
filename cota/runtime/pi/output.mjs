/** Recognize leaked provider protocol, never interpret it as executable tools. */
const markers = ['<｜｜DSML｜｜', '<||DSML||', '<DSML'];

export class PublicTextGuard {
  pending = '';
  run = '';
  runAtLineStart = false;
  quote = null;
  quoted = '';
  quoteLine = null;
  ticks = 0;
  indent = 0;
  slashes = 0;
  rejected = false;

  plain(text) {
    let output = '';
    for (const character of text) {
      if (this.rejected) break;
      this.pending += character;
      while (this.pending && !markers.some(marker => marker.startsWith(this.pending))) {
        output += this.pending[0];
        this.pending = this.pending.slice(1);
      }
      if (markers.includes(this.pending)) this.rejected = true;
    }
    return output;
  }

  openRun() {
    const delimiter = this.run;
    this.run = '';
    if (delimiter[0] === '~' && delimiter.length < 3) return this.plain(delimiter);
    const fenced = this.runAtLineStart && delimiter.length >= 3;
    this.quote = {delimiter, fenced,
      closing: fenced ? new RegExp(`^ {0,3}${delimiter[0]}{${delimiter.length},}[ \\t]*\\r?\\n$`) : null};
    this.quoted = delimiter;
    this.quoteLine = null; // The opening fence line cannot also be its closer.
    this.ticks = 0;
    return '';
  }

  consume(character) {
    if (this.run) {
      if (character === this.run[0]) {this.run += character; return '';}
      return this.openRun() + this.consume(character);
    }
    if (this.quote) {
      this.quoted += character;
      if (this.quote.fenced) {
        if (character === '\n') {
          if (this.quoteLine !== null && this.quote.closing.test(this.quoted.slice(this.quoteLine))) {
            const output = this.quoted;
            this.quote = null; this.quoted = ''; this.indent = 0;
            return output;
          }
          this.quoteLine = this.quoted.length;
        }
        return '';
      }
      if (character === '`') {this.ticks++; return '';}
      if (this.ticks === this.quote.delimiter.length) {
        const output = this.quoted.slice(0, -1);
        this.quote = null; this.quoted = ''; this.ticks = 0;
        return output + this.consume(character);
      }
      this.ticks = 0;
      return '';
    }
    if ((character === '`' && this.slashes % 2 === 0)
        || (character === '~' && this.indent >= 0 && this.indent <= 3)) {
      const output = this.pending;
      this.pending = '';
      this.run = character;
      this.runAtLineStart = this.indent >= 0 && this.indent <= 3;
      this.indent = -1; this.slashes = 0;
      return output;
    }
    this.indent = character === '\n' ? 0 : character === ' ' && this.indent >= 0 ? this.indent + 1 : -1;
    this.slashes = character === '\\' ? this.slashes + 1 : 0;
    return this.plain(character);
  }

  push(text) {
    let output = '';
    for (const character of text) {
      if (this.rejected) break;
      output += this.consume(character);
    }
    return output;
  }

  finish() {
    let output = this.run ? this.openRun() : '';
    if (this.quote) {
      // Fenced blocks may run to EOF. Inline spans require a real closing run;
      // hold them until resolved so unmatched/escaped ticks cannot leak markup.
      output += this.quote.fenced || this.ticks === this.quote.delimiter.length
        ? this.quoted : this.plain(this.quoted);
      this.quote = null; this.quoted = '';
    }
    // A truncated reserved marker is no more useful than a complete protocol dump.
    if (this.pending.length > 2) this.rejected = true;
    output += this.rejected ? '' : this.pending;
    this.pending = '';
    this.ticks = 0;
    return output;
  }
}

export function hasToolProtocol(message) {
  const guard = new PublicTextGuard();
  guard.push(message.content.filter(block => block.type === 'text').map(block => block.text).join('\n'));
  guard.finish();
  return guard.rejected;
}
