export type Json =
  | string
  | number
  | boolean
  | null
  | { [key: string]: Json | undefined }
  | Json[];

export interface Database {
  public: {
    Tables: {
      analytics_events: {
        Row: {
          id: number;
          user_id: string | null;
          event_name: string;
          properties: Json;
          created_at: string;
        };
        Insert: {
          id?: never;
          user_id?: string | null;
          event_name: string;
          properties?: Json;
          created_at?: string;
        };
        Update: Partial<Database["public"]["Tables"]["analytics_events"]["Insert"]>;
        Relationships: [];
      };
      profiles: {
        Row: {
          id: string;
          email: string | null;
          display_name: string | null;
          avatar_url: string | null;
          created_at: string;
          updated_at: string;
        };
        Insert: {
          id: string;
          email?: string | null;
          display_name?: string | null;
          avatar_url?: string | null;
          created_at?: string;
          updated_at?: string;
        };
        Update: Partial<Database["public"]["Tables"]["profiles"]["Insert"]>;
        Relationships: [];
      };
      projects: {
        Row: {
          id: string;
          user_id: string;
          source_url: string;
          title: string | null;
          status: string;
          progress: number;
          message: string;
          error: string | null;
          clip_count: number;
          target_duration: number;
          created_at: string;
          updated_at: string;
        };
        Insert: {
          id: string;
          user_id: string;
          source_url: string;
          title?: string | null;
          status?: string;
          progress?: number;
          message?: string;
          error?: string | null;
          clip_count: number;
          target_duration: number;
          created_at?: string;
          updated_at?: string;
        };
        Update: Partial<Database["public"]["Tables"]["projects"]["Insert"]>;
        Relationships: [];
      };
      project_clips: {
        Row: {
          id: string;
          project_id: string;
          user_id: string;
          filename: string;
          title: string;
          reason: string;
          start_time: number;
          end_time: number;
          version: number;
          edit_settings: Json | null;
          social_post: string | null;
          created_at: string;
          updated_at: string;
        };
        Insert: {
          id?: string;
          project_id: string;
          user_id: string;
          filename: string;
          title: string;
          reason: string;
          start_time: number;
          end_time: number;
          version?: number;
          edit_settings?: Json | null;
          social_post?: string | null;
          created_at?: string;
          updated_at?: string;
        };
        Update: Partial<Database["public"]["Tables"]["project_clips"]["Insert"]>;
        Relationships: [];
      };
      user_api_keys: {
        Row: {
          user_id: string;
          encrypted_key: string;
          nonce: string;
          key_last4: string;
          created_at: string;
          updated_at: string;
        };
        Insert: {
          user_id: string;
          encrypted_key: string;
          nonce: string;
          key_last4: string;
          created_at?: string;
          updated_at?: string;
        };
        Update: Partial<Database["public"]["Tables"]["user_api_keys"]["Insert"]>;
        Relationships: [];
      };
    };
    Views: Record<string, never>;
    Functions: Record<string, never>;
    Enums: Record<string, never>;
    CompositeTypes: Record<string, never>;
  };
}
