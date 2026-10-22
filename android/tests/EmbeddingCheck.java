package org.bibletalking.app;
import java.nio.file.*;
import java.util.*;
import org.json.*;
public class EmbeddingCheck {
    public static void main(String[] args) throws Exception {
        JSONArray fixtures=new JSONArray(Files.readString(Path.of(args[2])));
        try(Encoder encoder=new Encoder(args[0],Files.newInputStream(Path.of(args[1])))) {
            double worst=0;
            for(int i=0;i<fixtures.length();i++) {
                JSONObject f=fixtures.getJSONObject(i);String text=f.getString("text");
                long[] tokens=encoder.tokenizer.encode(text);JSONArray expected=f.getJSONArray("tokens");
                if(tokens.length!=expected.length())throw new AssertionError("Token count mismatch: "+i);
                for(int j=0;j<tokens.length;j++)if(tokens[j]!=expected.getLong(j))throw new AssertionError("Token mismatch: "+i+":"+j);
                float[] vector=encoder.encode(text);JSONArray reference=f.getJSONArray("vector");
                for(int j=0;j<vector.length;j++)worst=Math.max(worst,Math.abs(vector[j]-reference.getDouble(j)));
            }
            if(worst>0.0001)throw new AssertionError("Embedding differs: "+worst);
            System.out.println("PASS "+fixtures.length()+" tokenizer/embedding cases; max error="+worst);
        }
    }
}
