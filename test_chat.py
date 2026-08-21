"""Interaktif test — kullanici kendi testini yapabilir."""

import asyncio
from evidence.chat import ConversationManager

async def main():
    manager = ConversationManager()
    
    print("=" * 60)
    print("ARİ KAYNAK - Conversational Investigator Test")
    print("=" * 60)
    print()
    print("Komutlar:")
    print("  'cikis' veya 'q' → Çikis")
    print("  'sifirla'         → Session'i sifirla")
    print("  'durum'           → Mevcut durumu goster")
    print()
    
    while True:
        try:
            user_input = input("Sen: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGule gule!")
            break
        
        if not user_input:
            continue
        
        if user_input.lower() in ('cikis', 'q', 'quit', 'exit'):
            print("Gule gule!")
            break
        
        if user_input.lower() == 'sifirla':
            manager.reset()
            print("✓ Session sifirlandi.\n")
            continue
        
        if user_input.lower() == 'durum':
            stats = manager.get_stats()
            print(f"\n--- Durum ---")
            print(f"  Tur sayisi: {stats['turn_count']}")
            print(f"  Toplam sure: {stats['total_duration_ms']:.0f}ms")
            print(f"  Toplam kaynak: {stats['total_sources_found']}")
            print(f"  Intent dagilimi: {stats['intent_distribution']}")
            print()
            continue
        
        print("\n⏳ İşleniyor...")
        
        try:
            response = await manager.handle_message(user_input)
            print(f"\nAsistan: {response.text}")
            
            if response.follow_up_suggestions:
                print(f"\n💡 Öneriler:")
                for i, s in enumerate(response.follow_up_suggestions, 1):
                    print(f"   {i}. {s}")
            
            print()
        except Exception as e:
            print(f"\n❌ Hata: {e}\n")

if __name__ == "__main__":
    asyncio.run(main())
