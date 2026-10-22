package org.bibletalking.app;

import java.io.*;
import java.nio.charset.StandardCharsets;
import java.util.*;

/** Matches this model's BertNormalizer (case sensitive, no accent stripping) and WordPiece. */
public final class BertTokenizer {
    private final Map<String,Integer> vocab = new HashMap<>();
    private static final Set<String> SPECIAL = new HashSet<>(Arrays.asList("[UNK]", "[SEP]", "[PAD]", "[CLS]", "[MASK]"));
    public BertTokenizer(InputStream input) throws IOException {
        try (BufferedReader reader = new BufferedReader(new InputStreamReader(input, StandardCharsets.UTF_8))) {
            String line; int i=0; while ((line=reader.readLine()) != null) vocab.put(line,i++);
        }
    }
    private static boolean chinese(int c) {
        return (c>=0x4e00&&c<=0x9fff)||(c>=0x3400&&c<=0x4dbf)||(c>=0x20000&&c<=0x2a6df)
            ||(c>=0x2a700&&c<=0x2b73f)||(c>=0x2b740&&c<=0x2b81f)||(c>=0x2b820&&c<=0x2ceaf)
            ||(c>=0xf900&&c<=0xfaff)||(c>=0x2f800&&c<=0x2fa1f);
    }
    private static boolean punctuation(int c) {
        int t=Character.getType(c);
        return (c>=33&&c<=47)||(c>=58&&c<=64)||(c>=91&&c<=96)||(c>=123&&c<=126)
            ||t==Character.CONNECTOR_PUNCTUATION||t==Character.DASH_PUNCTUATION||t==Character.START_PUNCTUATION
            ||t==Character.END_PUNCTUATION||t==Character.INITIAL_QUOTE_PUNCTUATION
            ||t==Character.FINAL_QUOTE_PUNCTUATION||t==Character.OTHER_PUNCTUATION;
    }
    private void pieces(String word, List<Long> ids) {
        if (word.isEmpty()) return;
        if (SPECIAL.contains(word)) { ids.add((long)vocab.get(word)); return; }
        int[] chars=word.codePoints().toArray();
        if (chars.length>100) { ids.add((long)vocab.get("[UNK]")); return; }
        List<Long> parts=new ArrayList<>(); int start=0;
        while(start<chars.length) {
            int end=chars.length; Integer match=null;
            while(end>start) {
                match=vocab.get((start==0?"":"##")+new String(chars,start,end-start));
                if(match!=null) break; end--;
            }
            if(match==null) { ids.add((long)vocab.get("[UNK]")); return; }
            parts.add((long)match); start=end;
        }
        ids.addAll(parts);
    }
    public long[] encode(String text) {
        List<Long> ids=new ArrayList<>(); ids.add((long)vocab.get("[CLS]"));
        StringBuilder word=new StringBuilder();
        for(int i=0;i<text.length();) {
            String special=null;
            if(text.charAt(i)=='[') for(String s:SPECIAL) if(text.startsWith(s,i)) { special=s;break; }
            if(special!=null) { pieces(word.toString(),ids);word.setLength(0);pieces(special,ids);i+=special.length();continue; }
            int c=text.codePointAt(i);i+=Character.charCount(c); int t=Character.getType(c);
            if(c==0||c==0xfffd||((t==Character.CONTROL||t==Character.FORMAT)&&c!='\t'&&c!='\n'&&c!='\r')) continue;
            if(Character.isWhitespace(c)||t==Character.SPACE_SEPARATOR||chinese(c)||punctuation(c)) {
                pieces(word.toString(),ids);word.setLength(0);
                if(chinese(c)||punctuation(c)) pieces(new String(Character.toChars(c)),ids);
            } else word.appendCodePoint(c);
        }
        pieces(word.toString(),ids);
        if(ids.size()>511) ids=new ArrayList<>(ids.subList(0,511));
        ids.add((long)vocab.get("[SEP]"));
        long[] result=new long[ids.size()]; for(int i=0;i<result.length;i++) result[i]=ids.get(i); return result;
    }
}
