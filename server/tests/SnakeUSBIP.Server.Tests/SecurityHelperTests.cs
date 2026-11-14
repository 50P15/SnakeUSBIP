using System.Text.Json;
using SnakeUSBIP.Server.Services;
using Xunit;

namespace SnakeUSBIP.Server.Tests;

public class SecurityHelperTests
{
    [Theory]
    [InlineData("1-1", true)]
    [InlineData("1-2.3", true)]
    [InlineData("2-1.4.5", true)]
    [InlineData("", false)]
    [InlineData(null, false)]
    [InlineData("1-1; rm -rf", false)]
    [InlineData("1-1 & calc.exe", false)]
    [InlineData("invalid", false)]
    [InlineData("1-", false)]
    public void IsValidBusId_ValidatesCorrectly(string? busId, bool expected)
    {
        bool result = SecurityHelper.IsValidBusId(busId);
        Assert.Equal(expected, result);
    }

    [Theory]
    [InlineData("1-1", "1-1")]
    [InlineData("1-1;calc", "1-1calc")]
    [InlineData("test$(id)", "testid")]
    [InlineData(null, "")]
    [InlineData("", "")]
    [InlineData("safe-bus_id.1", "safe-bus_id.1")]
    public void SanitizeArgument_RemovesUnsafeCharacters(string? input, string expected)
    {
        string result = SecurityHelper.SanitizeArgument(input);
        Assert.Equal(expected, result);
    }

    [Theory]
    [InlineData(@"C:\Tools\test.txt", true)]
    [InlineData(@"..\..\Windows\system32", false)]
    [InlineData(@"C:\dir;rmdir", false)]
    [InlineData(@"C:\dir&calc", false)]
    [InlineData(null, false)]
    [InlineData("", false)]
    public void IsSafePath_DetectsTraversalsAndInjections(string? path, bool expected)
    {
        bool result = SecurityHelper.IsSafePath(path);
        Assert.Equal(expected, result);
    }

    [Fact]
    public void UpdateService_SelectServerAsset_PrefersServerSetupExe()
    {
        using var doc = JsonDocument.Parse(
            """
            [
              {"name":"SnakeUSBIP_Setup_v1.1.1.exe","browser_download_url":"https://example.com/client.exe"},
              {"name":"SnakeUSBIP-Server_Setup_v1.1.1.exe","browser_download_url":"https://example.com/server.exe"},
              {"name":"SHA256SUMS.txt","browser_download_url":"https://example.com/sums.txt"}
            ]
            """);

        var (url, name) = UpdateService.SelectServerAsset(doc.RootElement, isPortable: false);
        Assert.Equal("SnakeUSBIP-Server_Setup_v1.1.1.exe", name);
        Assert.Equal("https://example.com/server.exe", url);
    }
}
