// X2W_D3D12_RELEASE_RETIRED=1: a committed resource whose last guest reference is released gives up its
// desktop object once the GPU work submitted before that Release has completed, and not earlier.
//
// Stage 1 queues a copy behind a fence that nothing has signalled, releases the four resources it reads and
// writes, and checks that the budget keeps them in the retained column while the queue is held (negative
// control: an early free would drop them). Stage 2 signals the gate and checks the retained column returns
// to the baseline, or, with the switch off (argument "off"), that it still holds them as before the switch.
// Stage 3 releases a resource on an idle queue and a resource that stays referenced.
// The title-address part places a slot 133 texture and a slot 133 buffer with committed backing on title memory,
// releases them with the rest, and then places a new texture at the same title address: the address lookups
// (x2w_d3d12_address_lookup) must find the new wrapper and no entry of the old one.
#include "startup_stubs/resource_budget.h"

#include <d3d12sdklayers.h>
#include <dxgi1_6.h>
#include <wrl/client.h>

#include <array>
#include <cstdio>
#include <cstring>
#include <cwchar>

using Microsoft::WRL::ComPtr;
extern "C" __declspec(dllimport) HRESULT WINAPI D3D12XboxCreateDevice(IUnknown*, const void*, REFIID, void**);
extern "C" __declspec(dllimport) BOOL x2w_d3d12_budget_snapshot(x2w_budget::Snapshot*, SIZE_T);
extern "C" __declspec(dllimport) BOOL x2w_d3d12_address_lookup(unsigned long long, const D3D12_RESOURCE_DESC*, void**, unsigned*);

namespace {
using namespace x2w_budget;

template<class Result = HRESULT, class... Args>
Result invoke(IUnknown* object, unsigned slot, Args... args)
{
    using Call = Result (WINAPI*)(IUnknown*, Args...);
    return reinterpret_cast<Call>((*reinterpret_cast<void***>(object))[slot])(object, args...);
}

template<class T>
ComPtr<T> desktop_object(IUnknown* guest, ID3D12Device* device, IUnknown* object)
{
    // Same temporary private-data bridge as startup_resource_budget. The bridge reference is dropped on return.
    constexpr GUID key{0x0e34d52f, 0xd5a5, 0x4790, {0x91, 0xd4, 0x11, 0xa6, 0x7c, 0xbc, 0x2b, 0xc1}};
    ComPtr<T> output;
    if (FAILED(invoke(guest, 5, &key, object))) return output;
    ComPtr<IUnknown> reference;
    UINT bytes = sizeof(IUnknown*);
    const HRESULT hr = device->GetPrivateData(key, &bytes, reference.GetAddressOf());
    invoke(guest, 5, &key, static_cast<IUnknown*>(nullptr));
    if (SUCCEEDED(hr)) reference.As(&output);
    return output;
}

bool require(HRESULT hr, const char* stage)
{
    if (FAILED(hr)) std::printf("FAIL: %s hr=0x%08lx\n", stage, static_cast<unsigned long>(hr));
    return SUCCEEDED(hr);
}

bool snap(Snapshot& counts)
{
    if (x2w_d3d12_budget_snapshot(&counts, sizeof(counts))) return true;
    std::puts("FAIL: budget snapshot unavailable");
    return false;
}

bool same(Counts a, Counts b) { return a.bytes == b.bytes && a.objects == b.objects; }

bool matches(const Snapshot& expected, const Snapshot& actual, const char* stage)
{
    bool pass = expected.unmeasured == actual.unmeasured;
    if (!pass) std::printf("FAIL: %s unmeasured=%llu expected=%llu\n", stage, actual.unmeasured, expected.unmeasured);
    for (unsigned i = 0; i < category_count; ++i) {
        if (!same(expected.live[i], actual.live[i]) || !same(expected.retained[i], actual.retained[i])) {
            const auto a = actual.live[i], b = expected.live[i], c = actual.retained[i], d = expected.retained[i];
            std::printf("FAIL: %s %s live=%llu/%llu expected=%llu/%llu retained=%llu/%llu expected=%llu/%llu\n",
                        stage, names[i], a.bytes, a.objects, b.bytes, b.objects, c.bytes, c.objects, d.bytes, d.objects);
            pass = false;
        }
    }
    return pass;
}

ComPtr<IDXGIAdapter1> pick_adapter(IDXGIFactory4* factory, bool warp)
{
    ComPtr<IDXGIAdapter1> adapter;
    if (warp) {
        factory->EnumWarpAdapter(IID_PPV_ARGS(&adapter));
        return adapter;
    }
    wchar_t name[128]{};
    GetEnvironmentVariableW(L"XBOX2WINDOWS_ADAPTER", name, static_cast<DWORD>(std::size(name)));
    for (UINT i = 0; factory->EnumAdapters1(i, &adapter) == S_OK; ++i, adapter.Reset()) {
        DXGI_ADAPTER_DESC1 desc{};
        if (SUCCEEDED(adapter->GetDesc1(&desc)) && !(desc.Flags & DXGI_ADAPTER_FLAG_SOFTWARE) &&
            (!name[0] || std::wcsstr(desc.Description, name)) &&
            SUCCEEDED(D3D12CreateDevice(adapter.Get(), D3D_FEATURE_LEVEL_12_0, __uuidof(ID3D12Device), nullptr)))
            return adapter;
    }
    return nullptr;
}

// Waits on the desktop object behind a guest fence.
bool reaches(IUnknown* guest, ID3D12Device* device, IUnknown* fence, UINT64 value)
{
    const auto real = desktop_object<ID3D12Fence>(guest, device, fence);
    if (!real) return false;
    HANDLE done = CreateEventW(nullptr, FALSE, FALSE, nullptr);
    if (!done) return false;
    const bool reached = SUCCEEDED(real->SetEventOnCompletion(value, done)) &&
        WaitForSingleObject(done, 5000) == WAIT_OBJECT_0 && real->GetCompletedValue() >= value;
    CloseHandle(done);
    return reached;
}

int check(IUnknown* guest, ID3D12Device* device, ID3D12InfoQueue* debug, bool released)
{
    const D3D12_HEAP_PROPERTIES default_heap{D3D12_HEAP_TYPE_DEFAULT};
    const GUID& resource_iid = __uuidof(ID3D12Resource);
    const D3D12_RESOURCE_DESC texture_desc{D3D12_RESOURCE_DIMENSION_TEXTURE2D, 0, 256, 256, 1, 1, DXGI_FORMAT_R8G8B8A8_UNORM,
        {1, 0}, D3D12_TEXTURE_LAYOUT_UNKNOWN, D3D12_RESOURCE_FLAG_NONE};
    const D3D12_RESOURCE_DESC buffer_desc{D3D12_RESOURCE_DIMENSION_BUFFER, 0, 65536, 1, 1, 1, DXGI_FORMAT_UNKNOWN, {1, 0},
        D3D12_TEXTURE_LAYOUT_ROW_MAJOR, D3D12_RESOURCE_FLAG_NONE};
    const auto allocation_size = [&](const D3D12_RESOURCE_DESC& desc) {
        return device->GetResourceAllocationInfo(0, 1, &desc).SizeInBytes;
    };
    const UINT64 texture_bytes = allocation_size(texture_desc), buffer_bytes = allocation_size(buffer_desc);
    Snapshot baseline{};
    if (!snap(baseline)) return 4;

    const auto make_texture = [&](ComPtr<IUnknown>& out) {  // slot 127: the console committed-resource call
        return require(invoke(guest, 127, &default_heap, D3D12_HEAP_FLAG_NONE, &texture_desc, D3D12_RESOURCE_STATE_COMMON,
                              nullptr, nullptr, 0u, nullptr, &resource_iid, out.GetAddressOf()), "slot 127 texture");
    };
    const auto make_buffer = [&](ComPtr<IUnknown>& out) {  // slot 27: the desktop-shaped committed-resource call
        return require(invoke(guest, 27, &default_heap, D3D12_HEAP_FLAG_NONE, &buffer_desc, D3D12_RESOURCE_STATE_COMMON,
                              nullptr, &resource_iid, out.GetAddressOf()), "slot 27 buffer");
    };
    // Title memory: a texture at a page, and a buffer at an unaligned address (slot 133 then commits a copy).
    constexpr SIZE_T page = D3D12_DEFAULT_RESOURCE_PLACEMENT_ALIGNMENT;
    auto* title_memory = static_cast<char*>(VirtualAlloc(nullptr, page, MEM_RESERVE | MEM_COMMIT, PAGE_READWRITE));
    auto* title_buffer_memory = static_cast<char*>(VirtualAlloc(nullptr, page, MEM_RESERVE | MEM_COMMIT, PAGE_READWRITE));
    if (!title_memory || !title_buffer_memory) return 4;
    const auto place_texture = [&](ComPtr<IUnknown>& out) {  // slot 133 texture: committed stand-in, not aliased
        return require(invoke(guest, 133, title_memory, &texture_desc, D3D12_RESOURCE_STATE_COMMON, nullptr, &resource_iid,
                              out.GetAddressOf()), "slot 133 texture");
    };
    ComPtr<IUnknown> source_texture, dest_texture, source_buffer, dest_buffer, kept_texture, idle_texture;
    ComPtr<IUnknown> title_texture, title_buffer, replacement_texture;
    if (!make_texture(source_texture) || !make_texture(dest_texture) || !make_buffer(source_buffer)
        || !make_buffer(dest_buffer) || !make_texture(kept_texture) || !make_texture(idle_texture)
        || !place_texture(title_texture)
        || !require(invoke(guest, 133, title_buffer_memory + 16, &buffer_desc, D3D12_RESOURCE_STATE_COMMON, nullptr,
                           &resource_iid, title_buffer.GetAddressOf()), "slot 133 buffer")) return 4;
    const auto lookup = [&](unsigned& entries, void*& match) {
        match = nullptr;
        entries = ~0u;
        return x2w_d3d12_address_lookup(reinterpret_cast<unsigned long long>(title_memory), &texture_desc, &match, &entries) != FALSE;
    };

    const D3D12_COMMAND_QUEUE_DESC q{};
    const auto type = D3D12_COMMAND_LIST_TYPE_DIRECT;
    ComPtr<IUnknown> queue, allocator, list, gate, done, drain_allocator, drain_list;
    if (!require(invoke(guest, 8, &q, &__uuidof(ID3D12CommandQueue), queue.GetAddressOf()), "queue")
        || !require(invoke(guest, 9, type, &__uuidof(ID3D12CommandAllocator), allocator.GetAddressOf()), "allocator")
        || !require(invoke(guest, 73, &type, allocator.Get(), nullptr, &__uuidof(ID3D12GraphicsCommandList),
                           list.GetAddressOf()), "list")
        || !require(invoke(guest, 36, UINT64{0}, D3D12_FENCE_FLAG_NONE, &__uuidof(ID3D12Fence), gate.GetAddressOf()), "gate fence")
        || !require(invoke(guest, 36, UINT64{0}, D3D12_FENCE_FLAG_NONE, &__uuidof(ID3D12Fence), done.GetAddressOf()), "done fence")
        || !require(invoke(list.Get(), 139, allocator.Get(), nullptr), "list reset")
        || !require(invoke(guest, 9, type, &__uuidof(ID3D12CommandAllocator), drain_allocator.GetAddressOf()), "drain allocator")
        || !require(invoke(guest, 73, &type, drain_allocator.Get(), nullptr, &__uuidof(ID3D12GraphicsCommandList),
                           drain_list.GetAddressOf()), "drain list")
        || !require(invoke(drain_list.Get(), 9), "drain list close")) return 4;
    // The stand-in frees retired resources at the start of ExecuteCommandLists (and Present). An empty list
    // is the cheapest submission that reaches that point.
    const auto drain = [&] {
        IUnknown* empty[] = {drain_list.Get()};
        invoke<void>(queue.Get(), 10, 1u, empty);
    };
    // Guest CopyResource (list slot 17): the queue reads source and writes destination once the gate opens.
    invoke<void>(list.Get(), 17, dest_texture.Get(), source_texture.Get());
    invoke<void>(list.Get(), 17, dest_buffer.Get(), source_buffer.Get());
    if (!require(invoke(list.Get(), 9), "list close")) return 4;

    Snapshot expected = baseline, actual{};
    const auto live = [&](Category c, UINT64 bytes, int objects) {
        expected.live[c].bytes += bytes * objects;
        expected.live[c].objects += objects;
    };
    live(texture, texture_bytes, 5);  // source, destination, kept, idle, title-address texture
    live(buffer, buffer_bytes, 3);    // source, destination, title-address buffer
    if (!snap(actual) || !matches(expected, actual, "allocated")) return 5;

    // Queue Wait (slot 17) holds everything behind it until the gate fence reaches 1.
    if (!require(invoke(queue.Get(), 17, gate.Get(), UINT64{1}), "queue wait")) return 4;
    IUnknown* lists[] = {list.Get()};
    invoke<void>(queue.Get(), 10, 1u, lists);

    // Final guest Release of the four copy resources while the GPU work is still held.
    source_texture.Reset();
    dest_texture.Reset();
    source_buffer.Reset();
    dest_buffer.Reset();
    title_texture.Reset();
    title_buffer.Reset();
    const auto retain = [&](Category c, UINT64 bytes, int objects) {
        expected.live[c].bytes -= bytes * objects;
        expected.live[c].objects -= objects;
        expected.retained[c].bytes += bytes * objects;
        expected.retained[c].objects += objects;
    };
    retain(texture, texture_bytes, 3);
    retain(buffer, buffer_bytes, 3);
    for (int i = 0; i < 3; ++i) {
        drain();
        Sleep(50);
    }
    if (!snap(actual) || !matches(expected, actual, "released while the queue is held")) {
        std::puts("FAIL: a resource was freed before the work submitted ahead of its Release completed");
        return 5;
    }
    unsigned entries = 0;
    void* found = nullptr;
    if (!lookup(entries, found) || entries != 1 || found) {
        std::printf("FAIL: held: address lookup entries=%u match=%p, expected the released wrapper indexed and not found\n", entries, found);
        return 5;
    }
    std::puts("held: retained while the queue waits on the gate");

    // Open the gate; the done fence is signalled behind the held work on the same queue.
    if (!require(invoke(gate.Get(), 10, UINT64{1}), "gate signal")
        || !require(invoke(queue.Get(), 14, done.Get(), UINT64{1}), "queue signal")
        || !reaches(guest, device, done.Get(), 1)) return 4;
    drain();
    if (released) {
        // The retire marker of each Release was signalled before the done fence, so it has passed too.
        expected.retained[texture] = baseline.retained[texture];
        expected.retained[buffer] = baseline.retained[buffer];
        // The retained column counts what is left when the desktop object is destroyed. Nothing else holds one.
    }
    if (!snap(actual) || !matches(expected, actual, released ? "released after the queue passed" : "switch off keeps them")) {
        if (released) std::puts("FAIL: retained resources were not released after the queue passed their Release");
        return 5;
    }
    std::puts(released ? "released: retained returned to baseline after the queue completed"
                       : "off: the resources stay retained as before the switch");

    // Title-address reuse. The released wrapper must be gone from the address index (switch on) or still listed
    // but skipped (switch off); the new texture at the same address is the one the lookup returns.
    if (!lookup(entries, found) || entries != (released ? 0u : 1u) || found) {
        std::printf("FAIL: after release: address lookup entries=%u match=%p expected entries=%u and no match\n", entries, found,
                    released ? 0u : 1u);
        return 5;
    }
    if (!place_texture(replacement_texture)) return 4;
    live(texture, texture_bytes, 1);
    if (!lookup(entries, found) || found != static_cast<void*>(replacement_texture.Get()) || entries != (released ? 1u : 2u)) {
        std::printf("FAIL: reused address: lookup entries=%u match=%p expected entries=%u match=%p\n", entries, found,
                    released ? 1u : 2u, static_cast<void*>(replacement_texture.Get()));
        return 5;
    }
    std::printf("address reuse: %u index entr%s, the lookup returns the new wrapper\n", entries, entries == 1 ? "y" : "ies");
    if (!snap(actual) || !matches(expected, actual, "after address reuse")) return 5;

    // The queue is idle now. A resource released here is freed at a later drain without further GPU work. The
    // resource that stays referenced is never freed.
    idle_texture.Reset();
    expected.live[texture].bytes -= texture_bytes;
    --expected.live[texture].objects;
    if (released) {
        // Marker completion is asynchronous on an idle queue, so poll the drain point.
        bool settled = false;
        for (int i = 0; i < 400 && !settled; ++i) {
            drain();
            if (!snap(actual)) return 5;
            settled = same(actual.retained[texture], expected.retained[texture]) && same(actual.live[texture], expected.live[texture]);
            if (!settled) Sleep(5);
        }
        if (!matches(expected, actual, "idle queue release")) return 5;
        std::puts("released: idle-queue Release freed without further GPU work");
    } else {
        ++expected.retained[texture].objects;
        expected.retained[texture].bytes += texture_bytes;
        drain();
        if (!snap(actual) || !matches(expected, actual, "idle queue release, switch off")) return 5;
    }
    // kept_texture stayed referenced throughout: the snapshots above count it as live, never retained.

    const UINT64 errors = debug ? debug->GetNumStoredMessages() : 0;
    std::printf("debug_errors_or_warnings=%llu\n", errors);
    if (errors || FAILED(device->GetDeviceRemovedReason())) return 4;
    kept_texture.Reset();
    replacement_texture.Reset();
    std::puts(released ? "release-retired checks passed" : "switch-off checks passed");
    return 0;
}
}

int main(int argc, char** argv)
{
    if (argc < 2 || argc > 3 || (std::strcmp(argv[1], "warp") && std::strcmp(argv[1], "hardware"))
        || (argc == 3 && std::strcmp(argv[2], "off"))) return 2;
    ComPtr<IDXGIFactory4> factory;
    if (FAILED(CreateDXGIFactory1(IID_PPV_ARGS(&factory)))) return 3;
    const auto adapter = pick_adapter(factory.Get(), std::strcmp(argv[1], "warp") == 0);
    if (!adapter) return 77;
    char debug_env[2]{};
    const bool debug_on = GetEnvironmentVariableA("X2W_D3D12_DEBUG", debug_env, sizeof(debug_env)) && debug_env[0] == '1';
    if (debug_on) {
        ComPtr<ID3D12Debug> debug;
        if (FAILED(D3D12GetDebugInterface(IID_PPV_ARGS(&debug)))) return 77;
    }
    ComPtr<IUnknown> guest;
    ComPtr<ID3D12Device> device;
    std::array<unsigned char, 64> parameters{};
    if (!require(D3D12XboxCreateDevice(adapter.Get(), parameters.data(), __uuidof(ID3D12Device),
                                      reinterpret_cast<void**>(guest.GetAddressOf())), "Xbox device")
        || !require(D3D12CreateDevice(adapter.Get(), D3D_FEATURE_LEVEL_12_0, IID_PPV_ARGS(&device)), "desktop device")) return 3;
    ComPtr<ID3D12InfoQueue> debug;
    if (debug_on && FAILED(device.As(&debug))) return 3;
    if (debug) {
        D3D12_MESSAGE_SEVERITY severities[] = {
            D3D12_MESSAGE_SEVERITY_CORRUPTION, D3D12_MESSAGE_SEVERITY_ERROR, D3D12_MESSAGE_SEVERITY_WARNING};
        D3D12_INFO_QUEUE_FILTER filter{};
        filter.AllowList.NumSeverities = static_cast<UINT>(std::size(severities));
        filter.AllowList.pSeverityList = severities;
        if (FAILED(debug->AddStorageFilterEntries(&filter))) return 3;
        debug->ClearStoredMessages();
    }
    DXGI_ADAPTER_DESC1 desc{};
    adapter->GetDesc1(&desc);
    char switch_value[2]{};
    const bool switch_on = GetEnvironmentVariableA("X2W_D3D12_RELEASE_RETIRED", switch_value, sizeof(switch_value)) == 1 &&
        switch_value[0] == '1';
    const bool off_mode = argc == 3;
    if (switch_on == off_mode) {
        std::puts("FAIL: the X2W_D3D12_RELEASE_RETIRED environment does not match the requested mode");
        return 2;
    }
    std::printf("adapter=%ls debug_layer=%s mode=%s\n", desc.Description, debug ? "enabled" : "off", off_mode ? "off" : "on");
    return check(guest.Get(), device.Get(), debug.Get(), !off_mode);
}
